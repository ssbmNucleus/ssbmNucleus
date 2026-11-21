"""Exercise generated special physics as C, not a second Python model."""
import os,shutil,subprocess
from pathlib import Path
import pytest
from fighter_port.own_rivals_motion import physics
from fighter_port.own_windows import cancel_intervals

HEADER=r'''
#include <assert.h>
#include <math.h>
typedef struct {float X,Y;} Vec;
typedef struct {int ply,action_id;float facing_direction;
struct {int hitlag;} flags;
struct {float gravity,terminal_velocity,aerial_drift_stick_mult,aerial_drift_base,aerial_drift_max;} attr;
struct {int air_state;Vec self_vel,self_vel_ground;
float horzitonal_velocity_queue_will_be_added_to_0xec,vertical_velocity_queue_will_be_added_to_0xec;} phys;} FighterData;
typedef struct {void *userdata;} GOBJ;
static int t_frame[6];
void Fighter_SetAirborne(FighterData *f){f->phys.air_state=1;f->phys.self_vel_ground.X=0;}
void Fighter_PhysAir_ApplyGravity(FighterData *f,float g,float limit){f->phys.self_vel.Y-=g;if(f->phys.self_vel.Y < -limit)f->phys.self_vel.Y=-limit;}
void Fighter_PhysAir_ApplyAerialDrift(FighterData *f){f->phys.self_vel.X+=f->attr.aerial_drift_stick_mult;}
void Fighter_PhysGround_ApplyFriction(GOBJ *g){FighterData *f=g->userdata;f->phys.horzitonal_velocity_queue_will_be_added_to_0xec=-0.2f;}
void Fighter_PhysGround_ApplyVelocity(GOBJ *g){FighterData *f=g->userdata;f->phys.self_vel_ground.X=0;}
'''
MAIN=r'''
int main(void){
FighterData f={0};GOBJ g={&f};
f.action_id=300;f.facing_direction=1;f.attr.gravity=0.1f;f.attr.terminal_velocity=3;
f.attr.aerial_drift_stick_mult=0.2f;f.attr.aerial_drift_base=0.15f;f.attr.aerial_drift_max=2;
f.phys.self_vel_ground.X=4;t_frame[0]=1;TestPhys(&g);
assert(!f.phys.air_state && f.phys.self_vel_ground.X==0);
assert(f.phys.horzitonal_velocity_queue_will_be_added_to_0xec==0);
t_frame[0]=3;TestPhys(&g);assert(f.phys.air_state && f.phys.self_vel.Y>3.9f && f.phys.self_vel.X>0.9f);
t_frame[0]=4;TestPhys(&g);assert(f.phys.self_vel.Y<4 && f.phys.self_vel.Y>3.8f); // impulse does not restart
t_frame[0]=5;TestPhys(&g);assert(f.phys.self_vel.X==0 && f.phys.self_vel.Y==0); // held phase
t_frame[0]=8;TestPhys(&g);assert(f.phys.self_vel.Y<0 && f.phys.self_vel.X>0);
assert(f.attr.aerial_drift_base==0.15f && f.attr.aerial_drift_stick_mult==0.2f && f.attr.aerial_drift_max==2);
f.phys.air_state=0;f.facing_direction=-1;t_frame[0]=3;TestPhys(&g);assert(f.phys.self_vel.X< -0.9f);
f.flags.hitlag=1;t_frame[0]=4;TestPhys(&g);assert(f.phys.self_vel.Y==4);
return 0;}
'''


def example():
    def velocity(first,last,x,y,kind):
        return dict(real=first,last=last,x=x,y=y,x_kind=kind,y_kind=kind,modifiers=[])
    move=dict(windows=[(1,'Start',2),(3,'Rise',2),(5,'Hold',3),(8,'End',5)],
        momentum=[velocity(1,2,0,0,'ConstVelocity'),velocity(3,4,1,4,'SetVelocity'),
                  velocity(5,7,0,0,'ConstVelocity')])
    attack=dict(Windows=[dict(StringTableKey=name,MovementProperties=prop) for name,prop in [
        ('Start',dict(Gravity=0,CanDrift='::NoDrift')),('Rise',dict(CanDrift='::NoDrift')),
        ('Hold',dict(Gravity=0,CanDrift='::NoDrift')),('End',dict(AirAcceleration=0.5))]])
    return move,attack


def test_native_motion_launches_hangs_recovers_and_preserves_attributes(tmp_path):
    vc=Path('C:/Program Files/Microsoft Visual Studio/2022/Community/VC/Auxiliary/Build/vcvars64.bat')
    cc=shutil.which('cc') or shutil.which('gcc')
    if not (vc.is_file() or cc):pytest.skip('requires host C compiler')
    (tmp_path/'motion.c').write_text(HEADER+physics('TestPhys',{300:example()})+MAIN)
    if vc.is_file():
        batch=tmp_path/'run.cmd'
        batch.write_text('@echo off\ncall "'+str(vc)+'" >nul\nif errorlevel 1 exit /b 1\n'
            'cl /nologo /TC /std:c11 motion.c /Fe:motion.exe\nif errorlevel 1 exit /b 1\n'
            'motion.exe\nexit /b %errorlevel%\n')
        result=subprocess.run([os.environ['COMSPEC'],'/d','/c',str(batch)],cwd=tmp_path,capture_output=True,text=True,timeout=45)
    else:
        exe=tmp_path/'motion'
        result=subprocess.run([cc,'-std=c11',str(tmp_path/'motion.c'),'-o',str(exe)],capture_output=True,text=True,timeout=30)
        assert result.returncode==0,result.stdout+result.stderr
        result=subprocess.run([str(exe)],capture_output=True,text=True,timeout=10)
    assert result.returncode==0,result.stdout+result.stderr


def test_branch_guards_and_unhandled_velocity_cannot_become_unconditional():
    c=dict(WindowCancelType='::AttackDown',PostCancelWindowStringTableKey='Spin',WindowCancelPrerequisite='::None')
    move=dict(window_cancels=[dict(first=10,last=20,condition=c)])
    assert cancel_intervals(move,'Spin','AttackDown')==[(10,20)]
    c['WindowCancelPrerequisite']='::HasHit'
    with pytest.raises(ValueError,match='Guarded'):cancel_intervals(move,'Spin','AttackDown')
    move,attack=example();move['momentum'][0]['modifiers']=[dict(type='unknown')]
    with pytest.raises(ValueError,match='modifiers'):physics('TestPhys',{300:(move,attack)})
