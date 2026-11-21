from pathlib import Path
from types import SimpleNamespace
import os
import shutil
import subprocess
import pytest
from fighter_port import own_jab, code


def rows():
    return [dict(action=46,state=44,first=10,end=21,target=45,neutral=False),
            dict(action=47,state=45,first=8,end=18,target=46,neutral=True)]


def test_explicit_listeners_require_the_destination_clip_and_keep_empty_gates():
    actions=[SimpleNamespace(index=46,motion='Attack11',symbol='jab1'),
             SimpleNamespace(index=47,motion='Attack12',symbol='jab2')]
    profile=dict(id='attack11',motions=['Attack11'],jab_followup_windows=[[10,21]],jab_followup_neutral=[True])
    result=own_jab.collect([profile],actions)
    assert result==[dict(action=46,state=44,first=10,end=21,target=45,neutral=True)]
    with pytest.raises(ValueError,match='missing Attack12'):
        own_jab.collect([profile],actions[:1])
    profile['jab_followup_windows']=[];profile['jab_followup_neutral']=[]
    assert own_jab.collect([profile],actions)[0]['end']==1
    assert own_jab.collect([dict(id='attack11',motions=['Attack11'],jab_followup=10)],actions)==[]


HEADER='''#include <assert.h>
typedef struct GOBJ GOBJ;
typedef struct {int ply,state_id,action_id;float hitlag_mult;
struct {float frame;} state;
struct {int hitlag,x2218_2;} flags;
struct {int state_var1;} state_var;
struct {int down;struct {float X,Y;} lstick;} input;
struct {void (*IASA)(GOBJ *);} cb;} FighterData;
struct GOBJ {FighterData *userdata;};
#define HSD_BUTTON_A 256
static int calls,entered;
void Original(GOBJ *g){calls++;assert(g->userdata->hitlag_mult==0);assert(!g->userdata->flags.x2218_2);assert(!g->userdata->state_var.state_var1);}
void Different(GOBJ *g){}
void Enter2(GOBJ *g){entered=45;g->userdata->state_id=45;g->userdata->action_id=47;g->userdata->state.frame=0;g->userdata->cb.IASA=Original;}
void Enter3(GOBJ *g){entered=46;g->userdata->state_id=46;g->userdata->action_id=48;g->userdata->state.frame=0;g->userdata->cb.IASA=Different;}
'''
MAIN='''int main(void){FighterData f={0};GOBJ g={&f};f.state_id=44;f.action_id=46;f.cb.IASA=Original;
Jab_Load(&f);Jab_Frame(&f);assert(f.cb.IASA==Jab_IASA);
// An early press cannot latch the donor buffer and fire later after its release.
f.state.frame=9;f.input.down=HSD_BUTTON_A;f.hitlag_mult=10;f.flags.x2218_2=1;f.state_var.state_var1=1;
f.cb.IASA(&g);assert(!entered && calls==1);
f.state.frame=10;f.input.down=0;Jab_Frame(&f);f.cb.IASA(&g);assert(!entered);
// The current update's press opens exactly at frame 10, independent of the expired donor buffer.
f.input.down=HSD_BUTTON_A;f.cb.IASA(&g);assert(entered==45 && f.state.frame==0);
// A guarded second listener requires neutral stick, using the current input read after OnFrame.
Jab_Frame(&f);f.state.frame=8;f.input.lstick.X=0.8f;f.cb.IASA(&g);assert(entered==45);
f.input.lstick.X=0.15f;f.cb.IASA(&g);assert(entered==45);
f.input.lstick.X=0.149f;f.flags.hitlag=1;f.cb.IASA(&g);assert(entered==45);f.flags.hitlag=0;
f.state.frame=17.75f;f.cb.IASA(&g);assert(entered==46);
Jab_Frame(&f);assert(f.cb.IASA==Different);
// A closed window must stay closed even when the old opcode/buffer bits were already set.
f.state_id=44;f.action_id=46;f.cb.IASA=Original;f.state.frame=21;entered=0;
Jab_Frame(&f);f.flags.x2218_2=1;f.hitlag_mult=100;f.state_var.state_var1=1;f.cb.IASA(&g);assert(!entered);
// Unrelated action transitions keep their own callback.
f.state_id=14;f.action_id=14;f.cb.IASA=Different;Jab_Frame(&f);assert(f.cb.IASA==Different);
return 0;}
'''


def test_generated_jab_callbacks_use_current_press_and_both_interval_boundaries(tmp_path):
    vc=Path('C:/Program Files/Microsoft Visual Studio/2022/Community/VC/Auxiliary/Build/vcvars64.bat')
    cc=shutil.which('cc') or shutil.which('gcc')
    if not (vc.is_file() or cc):pytest.skip('requires host C compiler')
    body='\n'.join(own_jab.source(rows())).replace('((void (*)(GOBJ *))0x8008AE30)','Enter2').replace('((void (*)(GOBJ *))0x8008B194)','Enter3')
    (tmp_path/'jab.c').write_text(HEADER+body+MAIN)
    if vc.is_file():
        batch=tmp_path/'run.cmd'
        batch.write_text('@echo off\ncall "'+str(vc)+'" >nul\nif errorlevel 1 exit /b 1\n'
                         'cl /nologo /TC /std:c11 jab.c /Fe:jab.exe\nif errorlevel 1 exit /b 1\n'
                         'jab.exe\nexit /b %errorlevel%\n')
        result=subprocess.run([os.environ['COMSPEC'],'/d','/c',str(batch)],cwd=tmp_path,capture_output=True,text=True,timeout=45)
    else:
        exe=tmp_path/'jab'
        result=subprocess.run([cc,'-std=c11',str(tmp_path/'jab.c'),'-o',str(exe)],capture_output=True,text=True,timeout=30)
        assert result.returncode==0,result.stdout+result.stderr
        result=subprocess.run([str(exe)],capture_output=True,text=True,timeout=10)
    assert result.returncode==0,result.stdout+result.stderr


def test_generated_jab_module_compiles_in_normal_code_and_requires_load_reset():
    with pytest.raises(ValueError,match='OnLoad'):
        code.source('Marth',jabs=rows())
    kit=code.toolkit(os.environ.get('MEXTK_DIR') or str(Path.home() / 'projects' / 'm-ex' / 'MexTK'))
    if kit is None:pytest.skip('requires MexTK')
    tier2=pytest.importorskip('vault.echo.tier2.build')
    files,_=code.source('Marth',onload=0x801364AC,jabs=rows())
    assert 'Jab_Load(fd);' in files['fighter.c'] and 'Jab_Frame(fd);' in files['fighter.c']
    result=tier2.check_files(files,mextk_dir=str(kit))
    assert result.get('ok'),result.get('error')
