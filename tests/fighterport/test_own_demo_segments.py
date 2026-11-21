import json
import os
from types import SimpleNamespace
from pathlib import Path
import pytest
from fighter_port import own_demo_segments as segments,own_demo,own_bank,own_opacity,code
from test_own_demo import little_fighter,little_source,clip,FROZEN,FILES


def test_segments_cover_the_whole_source_with_a_shared_boundary_pose():
    job=dict(motion='Win1',parts=[dict(stem='victory')])
    parts=segments.jobs(job,389,6)
    ranges=[p['parts'][0]['keys'] for p in parts]
    assert ranges[0][0]==[0,0] and ranges[-1][-1][1]==389
    assert sum(k[-1][0] for k in ranges)==389
    assert all(a[-1][1]==b[0][1] for a,b in zip(ranges,ranges[1:]))
    assert job['parts']==[dict(stem='victory')]
    with pytest.raises(ValueError):segments.count_for(1000,5)
    with pytest.raises(ValueError):segments.jobs(dict(job,loop=True),389,6)


@pytest.mark.parametrize('aliases,difference',[(False,None),(True,None),(True,'opacity'),(True,'sounds')])
def test_full_native_demo_build_reuses_only_unentered_rows_and_clears_wait_loops(monkeypatch,tmp_path,aliases,difference):
    source=little_source()
    source.clip=lambda stem:SimpleNamespace(end=130)
    source.stems=lambda:['j02win1','a00wait1']+(['j02win2','j02win3'] if aliases else [])
    source.hash=lambda stem:'same-victory' if stem and stem.startswith('j02win') else stem
    monkeypatch.setattr(own_bank,'job_travel',lambda *args:({},None))
    monkeypatch.setattr(own_bank,'hold_pose',lambda *args:None)
    monkeypatch.setattr(own_demo,'_shares',lambda *args:None)
    if difference=='opacity':
        monkeypatch.setattr(own_opacity,'read',lambda *args:dict(clips={
            f'j02win{i}':dict(end=130,tracks={'Sash':[i/3]}) for i in (1,2,3)}))
    def script_for(line):
        if difference!='sounds' or line['motion']!='Win2':return None
        from vault.echo.subactions import COMMANDS,FighterDat
        sound=next(c for c,s in COMMANDS.items() if s.key=='sound_effect')
        return FighterDat.encode_script([(sound,{},None)])[0]
    refused=[]
    def make(source,symbol,job,keep,capacity,reducer=None):
        part=job['parts'][0]
        if part['stem'].startswith('j02win') and not part.get('keys'):
            refused.append(symbol)
            raise ValueError('too large. The full-duration clip cannot fit this rig.')
        end=part['keys'][-1][0] if part.get('keys') else 20
        blob=clip(symbol,end,len(source.target.order))
        return blob,dict(budget=.0003,bytes=len(blob),frames=end,stems=[part['stem']],
            tried=[dict(bytes=len(blob))],error=dict(whole=.001,between=.002))
    monkeypatch.setattr(own_bank,'make_clip',make)
    def hold(source,symbol,frames,pose,capacity):
        return make(source,symbol,dict(parts=[dict(stem='a00wait1',keys=[[0,0],[int(frames),0]])]),'',capacity)
    monkeypatch.setattr(own_bank,'make_hold',hold)
    pl,donor=little_fighter()
    new,files,report=own_demo.build(pl,FROZEN,'none','test',FILES,donor,source=source,
        continuations=True,cache=tmp_path,log=lambda *args:None,script_for=script_for)
    chain=report['continuations'][0]
    assert [s['row'] for s in chain['segments']]==[0,1]
    assert report['verify']['ok'] and own_demo.CAPACITY==0xB000
    assert not own_demo.demo_rows(new)[1]['flags'] & own_bank.LOOPS
    assert report['rows'][1]['source_first']==65 and report['rows'][1]['source_last']==130
    if aliases:
        assert [c['entry'] for c in report['continuations']]==[0,2,5]
        tails=[c['segments'][1]['row'] for c in report['continuations']]
        assert len(set(tails))==({'opacity':3,'sounds':2}.get(difference,1))
        assert report['rows'][2]['frames']==65 and report['rows'][5]['frames']==65
    else:
        assert report['rows'][2]['kind']=='HELD' and report['rows'][5]['kind']=='HELD'
    again=own_demo.build(pl,FROZEN,'none','test',FILES,donor,source=source,
        continuations=True,cache=tmp_path,log=lambda *args:None,script_for=script_for)[2]
    assert len(refused)==({'opacity':3,'sounds':2}.get(difference,1))
    assert again['continuations']==report['continuations']


def test_shared_tail_generates_one_transition_per_native_state():
    tail=[dict(row=1,frames=64),dict(row=3,frames=64)]
    report=dict(continuations=[dict(segments=[dict(row=i,frames=64)]+tail) for i in (0,2,5)])
    text='\n'.join(segments.code(None,report)['source'])
    assert text.count('case 1:')==1
    assert all(f'case {i}:' in text for i in (0,2,5))
    report['continuations'][1]['segments']=[dict(row=0,frames=65),dict(row=3,frames=64)]
    with pytest.raises(ValueError,match='conflicting'):
        segments.code(None,report)


def test_opacity_uses_segment_source_time_and_generated_runtime_is_demo_only():
    data=dict(bindings=[dict(mesh='Sash',default=1)],clips={'victory':dict(end=10,tracks={'Sash':[0]*6+[.2,.4,.6,.8,1]})})
    job=segments.jobs(dict(parts=[dict(stem='victory')]),10,2)[1]
    tracks=own_opacity.job_tracks(data,job,{'victory':10})
    assert tracks['Sash'][0]==(0.,0.) and tracks['Sash'][-1]==(5.,1.)
    report=dict(continuations=[dict(segments=[dict(row=0,frames=65),dict(row=1,frames=65)])])
    mine=segments.code(None,report);text='\n'.join(mine['source'])
    assert 'fd->ftaction != (FtAction *)(fd->ftData->x14)' in text
    assert 'fd->state.frame-65.0f,1,0,gobj,1,0,0' in text
    assert 'GObj_AddProc(gobj,DemoContinue,2)' in mine['load'][0]


def test_continuation_callback_compiles_with_native_abi():
    kit=code.toolkit(os.environ.get('MEXTK_DIR') or str(Path.home() / 'projects' / 'm-ex' / 'MexTK'))
    if kit is None:pytest.skip('MexTK not installed')
    tier2=pytest.importorskip('vault.echo.tier2.build')
    mine=segments.code(None,dict(continuations=[dict(segments=[dict(row=0,frames=64),dict(row=1,frames=65)])]))
    files,_=code.source('Marth',own=mine,onload=0x801363C4)
    result=tier2.check_files(files,mextk_dir=str(kit))
    assert result.get('ok'),result.get('error')
