from types import SimpleNamespace
import pytest
from shared.ingame import framestep,moves


class Emulator:
    def __init__(self,shadow_clear=.4,frame_delay=.1):
        self.clock=0.;self.shadow_clear=shadow_clear;self.frame_delay=frame_delay
        self.request=0;self.requested=None;self.frames=20;self.writes=[]
    def sleep(self,seconds):self.clock+=seconds
    def u8(self,address):
        if address==framestep.STEP_BITS:return self.request
        if address==framestep.STEP_SHADOW:return int(self.clock<self.shadow_clear)
        return 1
    def u32(self,address):
        if address!=framestep.FRAME_COUNTER:return 100
        if self.requested is not None and self.clock>=self.requested+self.frame_delay:
            self.frames+=1;self.requested=None;self.shadow_clear=self.clock+.1
        return self.frames
    def write_u8(self,address,value):
        self.writes.append((self.clock,address,value))
        assert address==framestep.STEP_BITS
        self.request=value
        if value&1:
            assert self.clock>=self.shadow_clear
            self.requested=self.clock


def install_clock(monkeypatch,d):
    monkeypatch.setattr(framestep,'time',SimpleNamespace(monotonic=lambda:d.clock,time=lambda:d.clock,sleep=d.sleep))


def test_existing_frame_budget_includes_handshake_rearming(monkeypatch):
    d=Emulator(shadow_clear=.4);install_clock(monkeypatch,d)
    assert framestep.step(d,3,timeout_per=1.)==3
    assert d.frames==23
    assert d.writes[0][0]>=.4
    assert all(address==framestep.STEP_BITS for _,address,_ in d.writes)


def test_stopped_handshake_is_bounded_without_a_request_or_free_run(monkeypatch):
    d=Emulator(shadow_clear=10.);install_clock(monkeypatch,d)
    assert framestep.step(d,8,timeout_per=1.)==0
    assert 1.<=d.clock<1.01 and not d.writes and d.frames==20


def test_rearm_and_step_share_one_budget_instead_of_each_getting_a_timeout(monkeypatch):
    d=Emulator(shadow_clear=.7,frame_delay=.6);install_clock(monkeypatch,d)
    assert framestep.step(d,1,timeout_per=1.)==0
    assert 1.<=d.clock<1.01 and d.frames==20


def test_mid_recipe_stall_is_reported_without_uncounted_recovery_frames(monkeypatch):
    runner=moves.MoveRunner.__new__(moves.MoveRunner);runner.d=object();runner.log=lambda *_:None
    state={'frames':20}
    fake=SimpleNamespace(snapshot=lambda d:dict(game_frames=state['frames']),step=lambda d,n:0,
        unfreeze=lambda d:pytest.fail('Recovery must not free-run uncounted frames'))
    monkeypatch.setattr(moves,'framestep',fake)
    with pytest.raises(moves.MoveError,match='0/8 frames ran'):runner._step(8)
    assert state['frames']==20
