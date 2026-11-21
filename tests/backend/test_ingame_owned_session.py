import os
from types import SimpleNamespace
import pytest
from tools.ingame import owned_session as owned


def fixture(monkeypatch):
    state={'exited':False,'closes':0}
    proc=SimpleNamespace(pid=999999,poll=lambda:0 if state['exited'] else None)
    boot=SimpleNamespace(proc=proc,pid=proc.pid,exe='C:/test/Slippi Dolphin.exe')
    def close(*,keep):
        assert keep;state['exited']=True;state['closes']+=1;return 'retained'
    session=SimpleNamespace(boot=boot,close=close)
    identity=dict(pid=proc.pid,parent=os.getpid(),exe=boot.exe,created=123.)
    monkeypatch.setattr(owned,'_identity',lambda pid:(identity,set()))
    return session,state,identity


def test_owned_child_closed_once_with_retained_logs(monkeypatch):
    session,state,identity=fixture(monkeypatch)
    r=owned.close_owned_session(session)
    assert state['closes']==1 and r['owned_process_exited']
    assert r['owned_process']['pid']==identity['pid']


@pytest.mark.parametrize('change',['parent','exe','pid','protected','ancestor','boot_pid'])
def test_uncertain_or_protected_process_never_closed(monkeypatch,change):
    session,state,identity=fixture(monkeypatch);protected=()
    if change=='parent':identity['parent']+=1
    elif change=='exe':identity['exe']='C:/test/msedgewebview2.exe'
    elif change=='pid':identity['pid']+=1
    elif change=='protected':protected=(identity['pid'],)
    elif change=='ancestor':monkeypatch.setattr(owned,'_identity',lambda pid:(identity,{pid}))
    else:session.boot.pid+=1
    with pytest.raises(RuntimeError):owned.close_owned_session(session,protected_pids=protected)
    assert state['closes']==0


def test_already_exited_retained_process_does_not_inspect_reused_pid(monkeypatch):
    session,state,_=fixture(monkeypatch);state['exited']=True
    monkeypatch.setattr(owned,'_identity',lambda pid:pytest.fail('No lookup of exited PID'))
    assert owned.close_owned_session(session)['owned_process'] is None


def test_artifact_writer_failure_cannot_skip_owned_cleanup(monkeypatch):
    session,state,_=fixture(monkeypatch);saved={}
    def save(name,value):
        if name=='samples.json':raise OSError('simulated output failure')
        saved[name]=value
    with pytest.raises(OSError,match='simulated output failure'):
        owned.persist_and_close(session,save,{'samples.json':[]})
    assert state['closes']==1 and saved['cleanup.json']['owned_process_exited']


def test_cleanup_receipt_write_failure_happens_after_child_exit(monkeypatch):
    session,state,_=fixture(monkeypatch)
    def save(name,value):raise OSError('disk unavailable')
    with pytest.raises(OSError):owned.persist_and_close(session,save,{})
    assert state['closes']==1 and state['exited']
