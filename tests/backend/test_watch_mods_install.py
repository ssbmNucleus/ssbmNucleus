"""Regression tests for watch_mods._install_selections costume-slot handling.

Replays recorded on a MODDED build can reference a costume index past the
vanilla roster (real repro: game_id 18257 in storage/nucleome.db — port 1 is
Fox costume 8, port 2 Fox costume 2). The watch flow builds a fresh project
from the VANILLA ISO, where Fox has only 4 costumes, so the historical
import→reorder(toIndex=8) died in MexCLI with "To index out of range" and the
whole watch job errored out. The fix pads with repeat imports of the same
costume zip until a copy lands exactly AT the replay's slot (imports append),
skipping reorder+remove in that branch.

The worker REST surface (worker.api) is faked — no MexCLI, no project.
"""
from tracker.replays.watch_mods import _install_selections

VANILLA_FOX_COSTUMES = 4


class FakeWorker:
    """Stateful stand-in for the build worker: imports append a costume,
    reorder swaps, remove deletes — mirroring the /api/mex endpoints the
    install path touches. Every call is recorded for assertions."""

    def __init__(self, counts=None):
        self.counts = dict(counts or {"Fox": VANILLA_FOX_COSTUMES})
        self.calls = []

    def api(self, method, route, body=None, timeout=None):
        self.calls.append((method, route, body))
        if route == "/api/mex/import":
            self.counts[body["fighter"]] += 1
            return {"success": True}
        if route.startswith("/api/mex/fighters/") and route.endswith("/costumes"):
            fighter = route.split("/")[-2]
            return {"costumes": [{"index": i} for i in range(self.counts[fighter])]}
        if route == "/api/mex/reorder":
            count = self.counts[body["fighter"]]
            assert body["fromIndex"] < count and body["toIndex"] < count, (
                f"reorder out of range: {body} with {count} costumes "
                "(the exact failure the padding fix prevents)"
            )
            return {"success": True}
        if route == "/api/mex/remove":
            self.counts[body["fighter"]] -= 1
            return {"success": True}
        raise AssertionError(f"unexpected worker call: {method} {route} {body}")

    def of(self, route):
        return [c for c in self.calls if c[1] == route]


def sel(slot):
    return {"fighter": "Fox", "slot": slot, "costume_path": "C:/vault/Fox/skin.zip"}


def test_slot_within_vanilla_range_reorders_and_removes():
    worker = FakeWorker()
    _install_selections(worker, [sel(1)], stage=None, project_dir=None)

    assert len(worker.of("/api/mex/import")) == 1
    (_, _, reorder), = worker.of("/api/mex/reorder")
    assert (reorder["fromIndex"], reorder["toIndex"]) == (4, 1)
    (_, _, remove), = worker.of("/api/mex/remove")
    assert remove["costumeIndex"] == 4
    assert worker.counts["Fox"] == VANILLA_FOX_COSTUMES + 1 - 1


def test_slot_past_roster_pads_with_imports_no_reorder():
    # the game 18257 port-1 case: Fox costume 8 against a 4-costume roster
    worker = FakeWorker()
    _install_selections(worker, [sel(8)], stage=None, project_dir=None)

    # 1 initial import (index 4) + 4 padding imports → the last copy IS index 8
    assert len(worker.of("/api/mex/import")) == 5
    assert worker.of("/api/mex/reorder") == []
    assert worker.of("/api/mex/remove") == []
    assert worker.counts["Fox"] == 9  # slot 8 exists


def test_second_low_slot_selection_after_padding_still_reorders():
    # game 18257 both ports: our Fox at slot 8, the opponent's Fox at slot 2
    worker = FakeWorker()
    _install_selections(worker, [sel(8), sel(2)], stage=None, project_dir=None)

    # padded roster is 9; the second skin appends at 9, swaps into 2,
    # displaced vanilla removed from 9 — the slot-8 copy stays put
    assert len(worker.of("/api/mex/import")) == 6
    (_, _, reorder), = worker.of("/api/mex/reorder")
    assert (reorder["fromIndex"], reorder["toIndex"]) == (9, 2)
    (_, _, remove), = worker.of("/api/mex/remove")
    assert remove["costumeIndex"] == 9
    assert worker.counts["Fox"] == 9
