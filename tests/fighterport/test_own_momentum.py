"""Source movement events execute on the entry update after current-input state transitions."""
from pathlib import Path
import os,shutil,subprocess
import pytest
from fighter_port import own_momentum as momentum,code


def event(kind='ConstVelocity',**kw):
    return dict(real=1,last=3,window='Active',x=3.2,y=0,x_kind=kind,y_kind='None',modifiers=[],**kw)


def test_source_events_keep_duration_units_and_custom_ownership():
    moves={'game_attackdash':dict(rivals2_attack='Dattack',momentum=[event()]),
           'game_specials':dict(rivals2_attack='Fspecial',momentum=[event()])}
    script=lambda stem,moves:'game_'+stem[3:]
    rows,receipt=momentum.collect({50:'c01attackdash',300:'d01specials'},moves,script,0.5)
    assert len(rows)==1 and rows[0]['x']==1.6 and rows[0]['first']==1 and rows[0]['last']==3
    assert rows[0]['action']==50 and not receipt['not_carried']
    moves['game_attackdash']['momentum']=[event('MultiplyVelocity')]
    rows,_=momentum.collect({50:'c01attackdash'},moves,script,0.5)
    assert rows[0]['x']==3.2  # factors never receive world scale or facing


def test_unknown_modifiers_and_compiled_axes_are_explicit_and_old_readers_are_rejected():
    m=dict(rivals2_attack='Dattack',momentum=[dict(event(),modifiers=[{'kind':'aim'}])])
    rows,receipt=momentum.collect({50:'x'}, {'game_attackdash':m},lambda *_:'game_attackdash')
    assert not rows and 'modifier' in receipt['not_carried'][0]['reason']
    m['momentum']=[dict(event(),x_kind='None',y_kind='None',y=4)]
    rows,receipt=momentum.collect({50:'x'}, {'game_attackdash':m},lambda *_:'game_attackdash')
    assert not rows and {r['axis'] for r in receipt['not_carried']}=={'x','y'}
    del m['momentum'][0]['last']
    with pytest.raises(ValueError,match='rerun the Rivals reader'):
        momentum.collect({50:'x'}, {'game_attackdash':m},lambda *_:'game_attackdash')


HEADER="""#include <assert.h>
typedef unsigned char u8;
typedef struct GOBJ GOBJ;
typedef struct {float X,Y;} Vec2;
typedef struct {int ply,state_id,action_id;float facing_direction;
struct {float frame;} state;struct {int hitlag;} flags;
struct {int air_state;Vec2 self_vel,self_vel_ground,anim_vel;
float horzitonal_velocity_queue_will_be_added_to_0xec,vertical_velocity_queue_will_be_added_to_0xec;} phys;
struct {void (*Phys)(GOBJ *);} cb;} FighterData;
struct GOBJ {FighterData *userdata;};
#define FTPRI_IASA 3
static void (*after_input)(GOBJ *);
static int registrations,physics_calls,interrupt;
void GObj_AddProc(GOBJ *g,void (*fn)(GOBJ *),int pri){assert(pri==3);after_input=fn;registrations++;}
void Fighter_PhysGround_ApplyVelocity(GOBJ *g){
g->userdata->phys.self_vel.X=g->userdata->phys.self_vel_ground.X;
g->userdata->phys.anim_vel.X=g->userdata->phys.horzitonal_velocity_queue_will_be_added_to_0xec;
}
void DifferentPhys(GOBJ *g){}
void OriginalPhys(GOBJ *g){
FighterData *f=g->userdata;physics_calls++;
if(interrupt){f->state_id=9;f->action_id=9;f->cb.Phys=DifferentPhys;return;}
float *x=&f->phys.self_vel_ground.X;
f->phys.horzitonal_velocity_queue_will_be_added_to_0xec=*x>0.2f?-0.2f:*x< -0.2f?0.2f:-*x;
Fighter_PhysGround_ApplyVelocity(g);
}
// The actual engine integrates both queues and animation velocity AFTER invoking the state's physics.
void Engine_Phys(GOBJ *g){FighterData *f=g->userdata;
f->cb.Phys(g);if(f->flags.hitlag)return;
f->phys.self_vel_ground.X+=f->phys.horzitonal_velocity_queue_will_be_added_to_0xec+
                         f->phys.vertical_velocity_queue_will_be_added_to_0xec;
f->phys.horzitonal_velocity_queue_will_be_added_to_0xec=0;
f->phys.vertical_velocity_queue_will_be_added_to_0xec=0;
f->phys.self_vel.X+=f->phys.anim_vel.X;f->phys.anim_vel.X=0;
}
"""
MAIN="""int main(void){FighterData f={0};GOBJ g={&f};f.facing_direction=1;
Momentum_Load(&f);Momentum_Register(&f,&g);Momentum_Register(&f,&g);assert(registrations==1);
// IASA enters a new attack before the registered process: frame-one constant motion is not missed.
f.state_id=f.action_id=50;f.state.frame=1;f.cb.Phys=OriginalPhys;
after_input(&g);Engine_Phys(&g);assert(f.phys.self_vel.X>3.19f && f.phys.self_vel.X<3.21f);
assert(physics_calls==1 && momentum_frame[0]==1);
f.flags.hitlag=1;after_input(&g);Engine_Phys(&g);assert(physics_calls==1 && momentum_frame[0]==1);
f.flags.hitlag=0;f.state.frame=3.5f;after_input(&g);Engine_Phys(&g);assert(f.phys.self_vel.X>3.19f);
f.state.frame=4;after_input(&g);Engine_Phys(&g);assert(f.phys.self_vel.X==0);
// An add impulse happens once, then ordinary friction continues even on fractional animation updates.
f.state.frame=5;after_input(&g);Engine_Phys(&g);assert(f.phys.self_vel.X>0.99f && f.phys.self_vel.X<1.01f);
f.state.frame=5.25f;after_input(&g);Engine_Phys(&g);assert(f.phys.self_vel.X>0.79f && f.phys.self_vel.X<0.81f);
// Re-entering after a different state re-arms frame-one events, with facing applied only to speeds.
f.state_id=f.action_id=14;f.state.frame=1;f.cb.Phys=DifferentPhys;after_input(&g);assert(f.cb.Phys==DifferentPhys);
f.state_id=f.action_id=50;f.state.frame=1;f.cb.Phys=OriginalPhys;f.facing_direction=-1;
after_input(&g);Engine_Phys(&g);assert(f.phys.self_vel.X< -3.19f);
// The old move's constant velocity cannot overwrite a physics-triggered state transition.
f.state.frame=2;interrupt=1;after_input(&g);Engine_Phys(&g);
assert(f.state_id==9 && f.cb.Phys==DifferentPhys);after_input(&g);assert(f.cb.Phys==DifferentPhys);
return 0;}
"""


def rows():
    return [dict(action=50,first=1,last=3,x_kind=4,y_kind=0,x=3.2,y=0),
            dict(action=50,first=4,last=4,x_kind=1,y_kind=0,x=0,y=0),
            dict(action=50,first=5,last=8,x_kind=2,y_kind=0,x=1.2,y=0)]


def test_actual_generated_movement_callbacks_on_entry_hitlag_and_interruption(tmp_path):
    vc=Path('C:/Program Files/Microsoft Visual Studio/2022/Community/VC/Auxiliary/Build/vcvars64.bat')
    cc=shutil.which('cc') or shutil.which('gcc')
    if not (vc.is_file() or cc):pytest.skip('requires host C compiler')
    (tmp_path/'momentum.c').write_text(HEADER+'\n'.join(momentum.source(rows()))+MAIN)
    if vc.is_file():
        batch=tmp_path/'run.cmd'
        batch.write_text('@echo off\ncall "'+str(vc)+'" >nul\nif errorlevel 1 exit /b 1\n'
                         'cl /nologo /TC /std:c11 momentum.c /Fe:momentum.exe\nif errorlevel 1 exit /b 1\n'
                         'momentum.exe\nexit /b %errorlevel%\n')
        r=subprocess.run([os.environ['COMSPEC'],'/d','/c',str(batch)],cwd=tmp_path,capture_output=True,text=True,timeout=45)
    else:
        exe=tmp_path/'momentum'
        r=subprocess.run([cc,'-std=c11',str(tmp_path/'momentum.c'),'-o',str(exe)],capture_output=True,text=True,timeout=30)
        assert r.returncode==0,r.stdout+r.stderr
        r=subprocess.run([str(exe)],capture_output=True,text=True,timeout=10)
    assert r.returncode==0,r.stdout+r.stderr


def test_movement_hooks_compile_with_native_kit_and_reset_through_the_normal_load(tmp_path):
    kit=code.toolkit(os.environ.get('MEXTK_DIR') or str(Path.home() / 'projects' / 'm-ex' / 'MexTK'))
    if kit is None:pytest.skip('requires MexTK')
    tier2=pytest.importorskip('vault.echo.tier2.build')
    files,provides=code.source('Marth',onload=0x801364AC,momentum=rows())
    assert 'Momentum_Load(fd);' in files['fighter.c'] and 'Momentum_Register(fd, gobj);' in files['fighter.c']
    result=tier2.check_files(files,mextk_dir=str(kit))
    assert result.get('ok'),result.get('error')


def test_engine_positioned_actions_remain_explicitly_unimplemented():
    m=dict(rivals2_attack='LedgeAttack',momentum=[event()])
    rows,receipt=momentum.collect({270:'g02cliffattack'}, {'game_cliffattack':m},lambda *_:'game_cliffattack')
    assert not rows and 'dedicated movement adapter' in receipt['not_carried'][0]['reason']


def test_movement_requires_reset_and_rejects_conflicting_animation_travel():
    with pytest.raises(ValueError,match='OnLoad'):
        code.source('Marth',momentum=rows())
    with pytest.raises(ValueError,match='both own actions'):
        code.source('Marth',onload=0x801364AC,momentum=rows(),slides=[50])
