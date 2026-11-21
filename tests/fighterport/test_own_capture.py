"""Run the generated hold code through lifecycle and interruption scenarios."""
import os,shutil,subprocess
from pathlib import Path
import pytest
from fighter_port.own_capture import SOURCE

HEADER=r'''
#include <assert.h>
typedef struct GOBJ {void *userdata;struct GOBJ *next;} GOBJ;
typedef struct {float X,Y,Z;} Vec;
typedef struct {int kind;Vec pos;struct {int var6;} item_var;} ItemData;
typedef struct {int state_id;struct {int sleep;} flags;
struct {GOBJ *attacker,*item;} grab;
struct {int down;Vec lstick;} input;
struct {int air_state;Vec self_vel,kb_vel,pos;} phys;
struct {void (*Anim)(GOBJ*);void (*IASA)(GOBJ*);void (*Phys)(GOBJ*);void (*Coll)(GOBJ*);} cb;
} FighterData;
#define ASID_WAIT 14
#define ASID_FALL 29
#define MATCHPLINK_ITEM 6
GOBJ *fighters[12],*list[8];GOBJ *(*stc_gobj_lookup)[8]=&list;
int falls;
static void NativePhys(GOBJ *g){}
GOBJ *Fighter_GetSubcharGObj(int p,int sub){return fighters[p*2+sub];}
void Fighter_SetAirborne(FighterData *fd){fd->phys.air_state=1;}
void Fighter_EnterFall(GOBJ *g){FighterData *fd=g->userdata;fd->state_id=ASID_FALL;fd->cb.Phys=NativePhys;falls++;}
'''
MAIN=r'''
int main(void){
    FighterData f={0};ItemData id={0};GOBJ target={&f,0},item={&id,0};int before;
    fighters[0]=&target;list[6]=&item;id.kind=99;id.item_var.var6=5;id.pos.X=20;id.pos.Y=35;
    f.state_id=ASID_WAIT;f.phys.kb_vel.X=3;
    assert(Hold_Begin(&target,&item,3,9));assert(f.phys.air_state && Hold_Uses(&target,&item));
    assert(f.phys.pos.X==20 && f.phys.pos.Y==26 && f.phys.kb_vel.X==0);
    id.pos.X=25;Hold_Phys(&target);assert(f.phys.pos.X==25);
    Hold_Anim(&target);Hold_Anim(&target);Hold_Anim(&target);
    assert(!Hold_Uses(&target,&item) && f.cb.Phys==NativePhys);
    // A new native hit owns callbacks. Do not replace its state with fall.
    assert(Hold_Begin(&target,&item,20,9));before=falls;
    f.state_id=75;f.cb.Phys=NativePhys;Hold_Release(&target);
    assert(f.state_id==75 && falls==before && !Hold_Uses(&target,&item));
    assert(Hold_Begin(&target,&item,20,9));list[6]=0;Hold_Phys(&target);
    assert(!Hold_Uses(&target,&item) && f.cb.Phys==NativePhys);
    // Reused item address with a different generation is not the old bubble.
    list[6]=&item;assert(Hold_Begin(&target,&item,20,9));id.item_var.var6++;
    Hold_Anim(&target);assert(!Hold_Uses(&target,&item));
    // Fresh buttons and alternating stick directions accelerate escape.
    assert(Hold_Begin(&target,&item,10,9));f.input.down=0x100;f.input.lstick.X=1;Hold_IASA(&target);
    f.input.lstick.X=-1;Hold_IASA(&target);assert(!Hold_Uses(&target,&item));
    f.grab.attacker=&target;assert(!Hold_Begin(&target,&item,20,9));f.grab.attacker=0;
    f.state_id=0;assert(!Hold_Begin(&target,&item,20,9));
    f.state_id=ASID_WAIT;fighters[0]=0;assert(!Hold_Begin(&target,&item,20,9));
    return 0;
}
'''


def test_native_hold_timeout_escape_interruption_and_item_reuse(tmp_path):
    vc=Path('C:/Program Files/Microsoft Visual Studio/2022/Community/VC/Auxiliary/Build/vcvars64.bat')
    cc=shutil.which('cc') or shutil.which('gcc')
    if not (vc.is_file() or cc):pytest.skip('requires host C compiler')
    (tmp_path/'capture.c').write_text(HEADER+SOURCE+MAIN)
    if vc.is_file():
        batch=tmp_path/'run.cmd'
        batch.write_text('@echo off\ncall "'+str(vc)+'" >nul\nif errorlevel 1 exit /b 1\n'
            'cl /nologo /TC /std:c11 capture.c /Fe:capture.exe\nif errorlevel 1 exit /b 1\n'
            'capture.exe\nexit /b %errorlevel%\n')
        result=subprocess.run([os.environ['COMSPEC'],'/d','/c',str(batch)],cwd=tmp_path,capture_output=True,text=True,timeout=45)
    else:
        exe=tmp_path/'capture'
        result=subprocess.run([cc,'-std=c11',str(tmp_path/'capture.c'),'-o',str(exe)],capture_output=True,text=True,timeout=30)
        assert result.returncode==0,result.stdout+result.stderr
        result=subprocess.run([str(exe)],capture_output=True,text=True,timeout=10)
    assert result.returncode==0,result.stdout+result.stderr
