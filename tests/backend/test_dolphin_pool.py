"""One pool of harness Dolphins per machine. Its size and its per-slot copies of
Dolphin come from one file beside the lock files, every tool takes the first
free slot, and a boot runs the copy of the slot it holds: two stock Slippi
Dolphins cannot both be driven through pipes, because the pipe names are
machine-wide. Nothing here boots Dolphin."""
import json
import os
import subprocess
import sys
import types

import pytest

from shared.ingame import boot, dolphin_lock, embed, melee_pipe

windows_only = pytest.mark.skipif(os.name != "nt", reason="slot copies of Dolphin are a Windows matter")


@pytest.fixture
def lock(tmp_path, monkeypatch):
    monkeypatch.setattr(dolphin_lock, "LOCK_PATH", tmp_path / "harness-dolphin.lock")
    for key in ("depth", "token", "slot"):
        monkeypatch.setitem(dolphin_lock._state, key, 0 if key == "depth" else None)
    for name in ("NUCLEUS_DOLPHIN_SLOTS", "NUCLEUS_DOLPHIN_SLOT_DIR", "NUCLEUS_SLIPPI_PATH"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(melee_pipe, "_PIPE_PREFIX", melee_pipe.STOCK_PIPE_PREFIX)
    yield dolphin_lock
    while dolphin_lock._state["depth"] > 0:
        dolphin_lock.release()


@pytest.fixture
def other_process():
    """A live pid that is not ours."""
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    yield proc.pid
    proc.kill()
    proc.wait()


def machine(lock, **keys):
    lock.LOCK_PATH.with_suffix(".json").write_text(json.dumps(keys), encoding="utf-8")


def kits(tmp_path, count):
    """A slot folder as the dev tool leaves it: <i>/Slippi Dolphin.exe and <i>/slot.json."""
    folder = tmp_path / "dolphin-slots"
    for index in range(count):
        (folder / str(index)).mkdir(parents=True)
        (folder / str(index) / dolphin_lock.KIT_EXE).write_bytes(b"MZ")
        (folder / str(index) / "slot.json").write_text(
            json.dumps({"slot": index, "prefix": "slipslot" + "ABCDEFGH"[index], "stock_exe": "stock.exe"}),
            encoding="utf-8")
    return folder


def booted(tmp_path, monkeypatch, exe="stock.exe"):
    monkeypatch.setattr(boot, "resolve_dolphin", lambda slippi: (exe, None))
    monkeypatch.setattr(boot, "pick_pipe_index", lambda max_index=8: 1)
    return boot.DolphinBoot("melee.iso", None, tmp_path / "runs")


def test_the_machine_file_says_how_many_slots_there_are(lock, monkeypatch):
    assert lock.slot_count() == 1
    monkeypatch.setenv("NUCLEUS_DOLPHIN_SLOTS", "6")
    assert lock.slot_count() == 6                       # no file: the environment, as before
    machine(lock, slots=3)
    assert lock.slot_count() == 3                       # the file is the machine's answer, whatever a tool set
    machine(lock, slots=99)
    assert lock.slot_count() == lock.MAX_SLOTS
    machine(lock, slots="many")
    assert lock.slot_count() == 1
    lock.LOCK_PATH.with_suffix(".json").write_text("not json", encoding="utf-8")
    assert lock.slot_count() == 6                       # an unreadable file is no file


def test_every_tool_counts_the_same_slots_so_the_first_free_one_is_taken(lock, other_process, monkeypatch):
    machine(lock, slots=3)
    monkeypatch.setenv("NUCLEUS_DOLPHIN_SLOTS", "1")    # a tool that used to keep to slot 0
    lock.slot_path(0).write_text(json.dumps({"pid": other_process, "purpose": "sibling", "token": "x"}),
                                 encoding="utf-8")
    assert lock.acquire("capture", wait=0)["slot"] == 1


@windows_only
def test_a_slots_copy_of_dolphin_is_read_from_the_machines_slot_folder(lock, tmp_path, monkeypatch):
    folder = kits(tmp_path, 2)
    assert lock.slot_kit(1) is None                     # the machine names no folder
    machine(lock, slots=2, slot_dir=str(folder))
    assert lock.slot_kit(1) == {"exe": str(folder / "1" / lock.KIT_EXE), "prefix": "slipslotB",
                                "stock_exe": "stock.exe"}
    assert lock.slot_kit(5) is None                     # no copy was made for that slot
    (folder / "0" / lock.KIT_EXE).unlink()
    assert lock.slot_kit(0) is None                     # half a copy is no copy
    (folder / "1" / "slot.json").write_text(json.dumps({"slot": 1, "prefix": "slipslotB"}), encoding="utf-8")
    assert lock.slot_kit(1) is None                     # a copy that does not say which Dolphin it is a copy of
    (folder / "1" / "slot.json").write_text(
        json.dumps({"slot": 0, "prefix": "slipslotA", "stock_exe": "stock.exe"}), encoding="utf-8")
    assert lock.slot_kit(1) is None                     # a folder that says it is another slot's

    machine(lock, slots=2)
    monkeypatch.setenv("NUCLEUS_DOLPHIN_SLOT_DIR", str(kits(tmp_path / "node", 1)))
    assert lock.slot_kit(0)["prefix"] == "slipslotA"    # a machine without the file: the environment


def test_pipe_names_follow_the_prefix(lock):
    assert melee_pipe.pipe_path(1) == r"\\.\pipe\slippibot1"
    melee_pipe.set_pipe_prefix("slipslotC")
    assert melee_pipe.pipe_path(2) == r"\\.\pipe\slipslotC2" and melee_pipe.pipe_prefix() == "slipslotC"
    melee_pipe.set_pipe_prefix()
    assert melee_pipe.pipe_path(1) == r"\\.\pipe\slippibot1"


@windows_only
def test_a_boot_runs_the_copy_of_the_slot_it_was_given(lock, tmp_path, monkeypatch, other_process):
    folder = kits(tmp_path, 2)
    machine(lock, slots=2, slot_dir=str(folder))
    lock.slot_path(0).write_text(json.dumps({"pid": other_process, "purpose": "sibling", "token": "x"}),
                                 encoding="utf-8")
    launched = []
    monkeypatch.setattr(boot.subprocess, "Popen",
                        lambda args, **k: launched.append(args) or types.SimpleNamespace(pid=4242, poll=lambda: 0))
    for name in ("set_active", "park", "clear_active"):
        monkeypatch.setattr(embed, name, lambda *a, **k: None)

    dolphin = booted(tmp_path, monkeypatch).prepare()
    assert dolphin.exe == "stock.exe"                   # no slot yet: nothing to say which copy
    dolphin.launch()                                    # takes the lock: slot 1, the first free one
    assert lock.current_slot() == 1
    assert launched[0][0] == str(folder / "1" / lock.KIT_EXE)
    assert melee_pipe.pipe_prefix() == "slipslotB" and dolphin.pipe_index == 1
    dolphin.cleanup()
    assert lock.current_slot() is None


@windows_only
def test_a_copy_stands_in_only_for_the_dolphin_it_was_copied_from(lock, tmp_path, monkeypatch):
    folder = kits(tmp_path, 2)
    machine(lock, slots=2, slot_dir=str(folder))
    lock.acquire("frameshot", wait=0)
    other = "D:/an/alternate/build/Slippi Dolphin.exe"          # e.g. named by NUCLEUS_SLIPPI_PATH
    dolphin = booted(tmp_path, monkeypatch, exe=other).prepare()
    assert dolphin.exe == other and melee_pipe.pipe_prefix() == "slippibot"
    assert dolphin.pipe_index == lock.slot_pipe(0)

    pinned = str(folder / "1" / lock.KIT_EXE)                   # a caller that names a slot copy itself keeps it
    assert booted(tmp_path, monkeypatch, exe=pinned).prepare().exe == pinned
    assert melee_pipe.pipe_prefix() == "slippibot"

    stock_elsewhere = str(tmp_path / "Slippi Launcher" / "netplay" / "stock.exe")
    for index in (0, 1):                                        # the same Dolphin written another way is the same
        (folder / str(index) / "slot.json").write_text(json.dumps(
            {"slot": index, "prefix": "slipslot" + "AB"[index], "stock_exe": stock_elsewhere.upper()}), encoding="utf-8")
    assert booted(tmp_path, monkeypatch, exe=stock_elsewhere.replace("\\", "/")).prepare().exe.endswith(lock.KIT_EXE)
    assert melee_pipe.pipe_prefix() == "slipslotA"


@windows_only
def test_a_later_boot_without_a_copy_is_back_on_the_stock_pipes(lock, tmp_path, monkeypatch):
    machine(lock, slots=2, slot_dir=str(kits(tmp_path, 2)))
    lock.acquire("first", wait=0)
    assert booted(tmp_path, monkeypatch).prepare().exe.endswith(lock.KIT_EXE)
    assert melee_pipe.pipe_prefix() == "slipslotA"
    machine(lock, slots=2)                              # the machine no longer keeps copies
    second = booted(tmp_path, monkeypatch).prepare()
    assert second.exe == "stock.exe" and melee_pipe.pipe_prefix() == "slippibot"


def test_pruning_spares_a_run_another_live_process_is_in(lock, tmp_path, monkeypatch, other_process):
    runs = tmp_path / "runs"
    old = [runs / f"test-20260101_00000{i}" for i in range(8)]
    for folder in old:
        folder.mkdir(parents=True)
    (old[0] / boot.RUN_OWNER).write_text(str(other_process), encoding="utf-8")     # the oldest, and still running
    (old[1] / boot.RUN_OWNER).write_text(str(os.getpid()), encoding="utf-8")       # ours, long finished
    (old[2] / boot.RUN_OWNER).write_text("999999999", encoding="utf-8")            # its process is gone

    mine = booted(tmp_path, monkeypatch).prepare()
    left = sorted(p.name for p in runs.iterdir() if p.is_dir())
    assert left == [old[0].name] + [p.name for p in old[3:]] + [mine.run_dir.name]
    assert boot.live_runs(runs) == [old[0].name]


def test_the_early_exe_line_says_when_the_slot_will_decide(lock, tmp_path, monkeypatch):
    lines = []

    def prepared():
        monkeypatch.setattr(boot, "resolve_dolphin", lambda slippi: ("stock.exe", None))
        monkeypatch.setattr(boot, "pick_pipe_index", lambda max_index=8: 1)
        del lines[:]
        boot.DolphinBoot("melee.iso", None, tmp_path / "runs", log=lines.append).prepare()
        return next(m for m in lines if m.startswith("Dolphin exe:"))

    assert prepared() == "Dolphin exe: stock.exe  (pipe slippibot1)"       # one slot: what it says is what runs
    machine(lock, slots=2)
    line = prepared()                                                      # several slots, none held yet
    assert line.startswith("Dolphin exe: stock.exe  (pipe slippibot1)") and "until launch takes a slot" in line
    lock.acquire("frameshot", wait=0)
    assert "until launch" not in prepared()                                # the slot is known: the line is final
