from types import SimpleNamespace
from devtools import frameshot as f


def test_startup_wait_retains_progress_diagnostics_without_claiming_a_healthy_counter_stalled(monkeypatch):
    messages=[];seen=[]
    monkeypatch.setattr(f.match_setup,'write_solo_player',lambda *a:None)
    monkeypatch.setattr(f.match_setup,'warp_to_stage_select',lambda *a:None)
    monkeypatch.setattr(f,'StageCursor',lambda *a:SimpleNamespace(wait_for_stage_select=lambda **k:True,force_select=lambda *a:True))
    monkeypatch.setattr(f,'wait_in_game',lambda *a,**k:True)
    def wait(d,n,log):
        seen.append(n);log('counter evidence retained');return False
    monkeypatch.setattr(f,'wait_game_frames',wait)
    monkeypatch.setattr(f,'liveness',lambda *a:('healthy','still advancing'))
    session=SimpleNamespace(d=object(),p=object(),alive=lambda:True)
    args=SimpleNamespace(stage='finaldestination')
    ok,reason=f.start_match(session,args,dict(ckind=0,color=0,label='test'),None,log=messages.append)
    assert not ok and seen==[f.READY_FRAMES]
    assert 'counter evidence retained' in messages
    assert 'required startup frame interval did not complete' in reason
    assert 'not advancing' not in reason
