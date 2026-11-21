"""Execute the actual generated C callbacks through Anim -> input refresh -> IASA."""
import importlib, re, subprocess, os, shutil
import pytest
from pathlib import Path

def function(module, text, name):
    source=text if module is None else getattr(importlib.import_module('fighter_port.'+module), text)
    match=re.search(r'(?:static )?(?:void|int) '+name+r'\([^)]*\)\s*\{', source)
    assert match, name
    start=match.start(); end=match.end(); level=1
    while level:
        level+=(source[end]=='{')-(source[end]=='}');end+=1
    return source[start:end]

header='''#include <assert.h>
typedef struct { float X,Y; } Vec2;
typedef struct { int ply,state_id; float facing_direction; struct {float frame;} state; struct {int held,down; Vec2 lstick;} input;
struct {int air_state; Vec2 self_vel;} phys; struct {int invisible;} flags; struct {float size;} hitbox[4]; } FighterData;
typedef struct {FighterData *userdata;} GOBJ;
static int t_frame[6], end_clip, state_changes, throws, n_held[6], n_full[6], bomb_wait[6];
static float rate=1;
#define B_BUTTON 0x200
#define N_HOLD 6
#define N_MOST 15
#define N_SWING 9
#define N_BIG 2
#define N_FIRE 12
#define FIREBALL 0
#define FIREBALL_FULL 1
#define N_END 40
#define N_END_AIR 40
#define S_THROW 17
#define S_END 40
#define S_END_AIR 40
#define BOMB_AGAIN 95
int Tick(GOBJ *g){return ++t_frame[g->userdata->ply];}
int FrameTimerCheck(GOBJ *g){return !end_clip;}
void Fighter_SetAnimRate(GOBJ *g,float v){rate=v;}
void Shoot(GOBJ *g,int full){}
void Leave(GOBJ *g,int a,int b){state_changes++;}
void Throw(GOBJ *g){throws++; assert(g->userdata->input.lstick.X==1); bomb_wait[g->userdata->ply]=0;}
'''
PROGRAMS = {}

cloud_header=header+"""
static int charge_age[6],charge_armed[6],accept_cancel;
static float limit[6];
#define LIMIT_PER_FRAME 0.01f
#define CHARGE_AGAIN 10
#define ST_CHARGE_LOOP 70
#define ST_CHARGE_END 71
#define CANCEL_BUTTONS 0x10
void Enter(GOBJ *g,int state){g->userdata->state_id=state;state_changes++;}
void Fighter_IASACheck_AllGrounded(GOBJ *g){if(accept_cancel)g->userdata->state_id=20;}
int Fighter_IASACheck_AllAerial(GOBJ *g){if(accept_cancel)g->userdata->state_id=21;return accept_cancel;}
"""
cloud='\n'.join(function('own','CLOUD',n).replace('{{','{').replace('}}','}') for n in
                ('Charge_Count','ChargeStart_IASA','ChargeStart_Anim','ChargeLoop_Anim','ChargeLoop_IASA'))
cloud_main="""int main(void){FighterData f={0};GOBJ g={&f};
f.state_id=ST_CHARGE_LOOP;charge_age[0]=9;ChargeLoop_Anim(&g);f.input.down=B_BUTTON;ChargeLoop_IASA(&g);
assert(f.state_id==ST_CHARGE_END && charge_age[0]==10 && limit[0]>0.009f && limit[0]<0.011f);
for(int air=0;air<2;air++){
  f.phys.air_state=air;f.state_id=ST_CHARGE_LOOP;f.input.down=0;accept_cancel=1;
  ChargeLoop_Anim(&g);f.input.down=CANCEL_BUTTONS;ChargeLoop_IASA(&g);
  assert(f.state_id==(air?21:20));
  f.state_id=ST_CHARGE_LOOP;accept_cancel=0;ChargeLoop_IASA(&g);assert(f.state_id==ST_CHARGE_END);
}
// Arming sees the refreshed neutral stick, not the held direction that entered the move.
f.input.down=0;f.input.lstick.X=1;charge_armed[0]=0;ChargeStart_Anim(&g);
f.input.lstick.X=0;ChargeStart_IASA(&g);assert(charge_armed[0]);
// An animation loop and its IASA update must not add two frames of charge.
f.state_id=ST_CHARGE_LOOP;end_clip=1;limit[0]=0;charge_age[0]=0;
ChargeLoop_Anim(&g);ChargeLoop_IASA(&g);assert(charge_age[0]==1 && f.state_id==ST_CHARGE_LOOP);
return 0;}
"""
PROGRAMS['cloud']=cloud_header+cloud+cloud_main

ike_header=header+"""
static int qd_charge[6];
#define QD_MAX 70
int Qd(FighterData *f,int part){return 80+10*f->phys.air_state+part;}
void Enter(GOBJ *g,int state){g->userdata->state_id=state;state_changes++;}
"""
ike='\n'.join(function('own','IKE',n).replace('{{','{').replace('}}','}') for n in ('QdHold_Anim','QdHold_IASA'))
ike_main="""int main(void){FighterData f={0};GOBJ g={&f};
for(int air=0;air<2;air++){
 f.phys.air_state=air;f.state_id=Qd(&f,1);f.input.held=B_BUTTON;qd_charge[0]=5;
 QdHold_Anim(&g);assert(f.state_id==Qd(&f,1));f.input.held=0;QdHold_IASA(&g);
 assert(f.state_id==Qd(&f,2) && qd_charge[0]==6);
 f.state_id=Qd(&f,1);qd_charge[0]=QD_MAX;f.input.held=0;end_clip=1;
 QdHold_Anim(&g);f.input.held=B_BUTTON;QdHold_IASA(&g);
 assert(f.state_id==Qd(&f,1) && qd_charge[0]==QD_MAX);
}return 0;}
"""
PROGRAMS['ike']=ike_header+ike+ike_main

# Greninja's Leave helper has two arguments; the other test programs use Ittle's three.

from fighter_port import states as state_helpers
wrapper_header=header+"""
static int prior_calls;
void BeforeInput(FighterData *fd,GOBJ *g){if(fd->input.down & B_BUTTON)fd->state_id=99;}
void OriginalIASA(GOBJ *g){prior_calls++;}
"""
wrapper='\n'.join(state_helpers.iasa_wrapper('WrappedIASA','BeforeInput','OriginalIASA'))
wrapper_main="""int main(void){FighterData f={0};GOBJ g={&f};
f.state_id=20;WrappedIASA(&g);assert(prior_calls==1 && f.state_id==20);
f.input.down=B_BUTTON;WrappedIASA(&g);assert(prior_calls==1 && f.state_id==99);
return 0;}
"""
PROGRAMS['wrapper']=wrapper_header+wrapper+wrapper_main

dive_header=header+"""
static int dive_asked[6];
#define ST_RISE 30
#define ST_RISE_AIR 31
#define ST_DIVE 32
void Enter(GOBJ *g,int state){g->userdata->state_id=state;}
void Fighter_SetAirborne(FighterData *fd){fd->phys.air_state=1;}
"""
dive=function('own','CLOUD','OwnInput').replace('{{','{').replace('}}','}')
dive=dive.replace('{rise_more}','').replace('{rise_from}','11').replace('{rise_last}','23')
dive_main="""int main(void){FighterData f={0};GOBJ g={&f};
for(int air=0;air<2;air++){
 f.state_id=air?ST_RISE_AIR:ST_RISE;f.state.frame=10;f.input.down=B_BUTTON;dive_asked[0]=0;
 OwnInput(&f,&g);assert(!dive_asked[0]);
 f.state.frame=11;OwnInput(&f,&g);assert(dive_asked[0]);
 f.state.frame=23;f.input.down=0;OwnInput(&f,&g);assert(f.state_id==ST_DIVE && f.phys.air_state);
}return 0;}
"""
PROGRAMS['cloud_dive']=dive_header+dive+dive_main

byleth_header=header+"""
static int bow_age[6],bow_wait[6],axe_turned[6],turns;
#define BOW_CANCEL_FROM 4
#define BOW_CANCEL_TO 20
#define BOW_TURN_WAIT 3
#define SHIELD_BUTTONS 0x10
#define ST_BOW_CANCEL 40
#define ST_AXE_CANCEL 41
#define AXE_COMMIT 40
#define AXE_TURN_FROM 12
#define AXE_TURN_TO 41
void Enter(GOBJ *g,int state){g->userdata->state_id=state;}
void Turn_Round(FighterData *f){turns++;f->facing_direction*=-1;}
int Fighter_IASACheck_JumpF(GOBJ *g){return 0;}
int Fighter_IASACheck_JumpAerial(GOBJ *g){return 0;}
"""
byleth=function('own','BYLETH','OwnInput').replace('{{','{').replace('}}','}')
byleth=byleth.replace('{bow_states}','s==10 || s==11').replace('{bow_held}','s==11').replace('{axe_states}','s==20')
byleth_main="""int main(void){FighterData f={0};GOBJ g={&f};
f.state_id=10;bow_age[0]=3;f.input.down=SHIELD_BUTTONS;OwnInput(&f,&g);assert(f.state_id==10);
bow_age[0]=4;OwnInput(&f,&g);assert(f.state_id==ST_BOW_CANCEL);
f.state_id=20;f.state.frame=39;OwnInput(&f,&g);assert(f.state_id==ST_AXE_CANCEL);
f.state_id=20;f.state.frame=40;OwnInput(&f,&g);assert(f.state_id==20);
f.input.down=0;f.state.frame=12;f.facing_direction=1;f.input.lstick.X=-1;OwnInput(&f,&g);
assert(turns==1 && axe_turned[0]);f.input.lstick.X=1;OwnInput(&f,&g);assert(turns==1);
return 0;}
"""
PROGRAMS['byleth']=byleth_header+byleth+byleth_main

from fighter_port import code as generated_code
reverse_rows=([dict(action=295,flags=0,move=0,bits=0,anim=0,iasa='OriginalIASA',phys=0,coll=0,camera=0)],[])
reverse_code=generated_code.source('Marth',reverse=[341],state_rows=reverse_rows)[0]['fighter.c']
reverse_header=header+"""
static int prior_calls,turns;
void Fighter_SetBoneRotY(FighterData *f,int bone,float angle){turns++;}
void OriginalIASA(GOBJ *g){prior_calls++;}
"""
reverse='\n'.join(function(None,reverse_code,n) for n in ('ReverseInput','Reverse_IASA_341'))
reverse_main="""int main(void){FighterData f={0};GOBJ g={&f};
f.state_id=341;f.state.frame=4;f.facing_direction=1;f.phys.self_vel.X=3;
// The refreshed stick reverses facing and momentum on the final eligible update.
f.input.lstick.X=-1;Reverse_IASA_341(&g);assert(turns==1 && prior_calls==1);
assert(f.facing_direction==-1 && f.phys.self_vel.X==-3);
// Same held direction cannot repeatedly flip; the next update is outside the window.
Reverse_IASA_341(&g);assert(turns==1 && prior_calls==2);
f.state.frame=5;f.input.lstick.X=1;Reverse_IASA_341(&g);assert(turns==1 && prior_calls==3);
return 0;}
"""
PROGRAMS['reverse']=reverse_header+reverse+reverse_main


VC=Path('C:/Program Files/Microsoft Visual Studio/2022/Community/VC/Auxiliary/Build/vcvars64.bat')
CC=shutil.which('cc') or shutil.which('gcc')


@pytest.mark.skipif(not (VC.is_file() or CC), reason='requires an installed host C compiler')
def test_actual_callbacks_use_current_inputs_without_advancing_the_animation_clock_twice(tmp_path):
    for name, source in PROGRAMS.items():
        (tmp_path/(name+'.c')).write_text(source,'utf-8')
    if VC.is_file():
        batch=tmp_path/'run.cmd'
        lines=['@echo off', 'call "'+str(VC)+'" >nul', 'if errorlevel 1 exit /b 1']
        for name in PROGRAMS:
            lines += [f'cl /nologo /TC /std:c11 /W3 {name}.c /Fe:{name}.exe',
                      'if errorlevel 1 exit /b 1', name+'.exe', 'if errorlevel 1 exit /b 1']
        batch.write_text('\n'.join(lines+['exit /b 0','']))
        r=subprocess.run([os.environ['COMSPEC'],'/d','/c',str(batch)],cwd=tmp_path,capture_output=True,text=True,timeout=90)
        assert r.returncode==0, r.stdout+r.stderr
    else:
        for name in PROGRAMS:
            exe=tmp_path/name
            r=subprocess.run([CC,'-std=c11',str(tmp_path/(name+'.c')),'-o',str(exe)],capture_output=True,text=True,timeout=30)
            assert r.returncode==0, r.stdout+r.stderr
            r=subprocess.run([str(exe)],capture_output=True,text=True,timeout=10)
            assert r.returncode==0, r.stdout+r.stderr


def test_cloud_and_ike_register_the_input_callbacks():
    from fighter_port import own
    text=Path(own.__file__).read_text('utf-8')
    for stem in ('ChargeStart','ChargeLoop','QdHold'):
        assert f"'anim': '{stem}_Anim', 'iasa': '{stem}_IASA'" in text


