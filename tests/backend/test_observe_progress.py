from types import SimpleNamespace
import pytest
from shared.ingame import observe


class Clock:
    def __init__(self):self.value=0.
    def monotonic(self):return self.value
    def sleep(self,n):self.value+=n


def setup(monkeypatch, counter, alive=lambda:True):
    clock=Clock()
    monkeypatch.setattr(observe,'time',clock)
    d=SimpleNamespace(u32=lambda _:counter(clock.value),alive=lambda:alive())
    return clock,d


def test_slow_counter_must_complete_every_requested_frame(monkeypatch):
    clock,d=setup(monkeypatch,lambda t:int(t/2))
    assert observe.wait_game_frames(d,10,poll=.25)
    assert clock.value==20. # Old total deadline was 3s; no frames were skipped.


def test_stalled_and_unreadable_counters_do_not_pass(monkeypatch):
    clock,d=setup(monkeypatch,lambda _:4)
    assert not observe.wait_game_frames(d,10,poll=.25)
    assert clock.value==3.
    clock,d=setup(monkeypatch,lambda _:None)
    assert not observe.wait_game_frames(d,10) and clock.value==0


def test_dead_process_cannot_be_rescued_by_counter_values(monkeypatch):
    clock,d=setup(monkeypatch,lambda t:int(t*10),alive=lambda:False)
    assert not observe.wait_game_frames(d,10) and clock.value==0


def test_repeated_scene_resets_remain_absolutely_bounded(monkeypatch):
    clock,d=setup(monkeypatch,lambda t:int(t)%3)
    assert not observe.wait_game_frames(d,5,poll=.25)
    assert clock.value==15.
