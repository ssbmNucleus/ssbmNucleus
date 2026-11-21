"""core.child_procs bookkeeping, with no real process: own() forgets children
that have been waited on, so the export, patch and setup helpers every job
hands it (one or more per job) do not pile up for the life of the backend.
The kill-with-the-parent behaviour itself is test_child_procs.py (slow)."""
from tests.paths import BACKEND
import sys

sys.path.insert(0, str(BACKEND))

from core import child_procs as cp


class _Proc:
    def __init__(self, pid, returncode=None):
        self.pid, self.returncode = pid, returncode

    def poll(self):
        return self.returncode


def test_own_forgets_children_that_were_waited_on(monkeypatch):
    monkeypatch.setattr(cp, '_owned', [])
    monkeypatch.setattr(cp, '_assign', lambda proc: False)
    first, second = _Proc(101), _Proc(102)
    assert cp.own(first) is first
    cp.own(second)
    assert cp._owned == [first, second]

    first.returncode = 0          # its job waited on it and ended
    third = cp.own(_Proc(103))
    assert cp._owned == [second, third]
    assert cp.owned_pids() == [102, 103]


def test_a_child_still_running_is_kept_for_the_sweep(monkeypatch):
    monkeypatch.setattr(cp, '_owned', [])
    monkeypatch.setattr(cp, '_assign', lambda proc: False)
    running = cp.own(_Proc(201))
    last = None
    for pid in range(202, 210):        # helpers that each ran and exited
        last = cp.own(_Proc(pid, returncode=1))
    # Only the newest finished one is still listed (pruned on the next own).
    assert cp._owned == [running, last]
    assert cp.owned_pids() == [201]
