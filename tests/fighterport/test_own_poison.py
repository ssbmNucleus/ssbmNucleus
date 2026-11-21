"""Execute the generated status/contact code, including independent opponents."""
import os,shutil,subprocess
from pathlib import Path
import pytest
from echo_rivals2.rules import POISON
from fighter_port import own_poison

HEADER=r'''
#include <assert.h>
#include <string.h>
typedef unsigned char u8;
typedef unsigned short u16;
typedef struct GOBJ GOBJ;
typedef struct {void *x14;} FtData;
typedef void FtAction;
typedef struct {u8 abi[0x2070];int ply,kind,state_id,action_id,atk_kind;float percent;
struct {float frame;} state;struct {int sleep;} flags;void *ftaction;FtData *ftData;
struct {float percent_temp,tip_force_applied;struct {GOBJ *source;float force_applied;} hit_log;} dmg;
struct {int dmg_taken2;GOBJ *dmg_source;} shield;} FighterData;
typedef struct {int kind;} ItemData;
struct GOBJ {int entity_class;void *userdata;};
#define ASID_WAIT 14
#define FTPRI_DMGAPPLY 14
static GOBJ *fighters[6][2],helpers[2];static int created;
GOBJ *Fighter_GetGObj(int p){return fighters[p][0];}
GOBJ *Fighter_GetSubcharGObj(int p,int sub){return fighters[p][sub];}
GOBJ *GObj_Create(int kind,int link,int priority){assert(link==0 && created<2);return &helpers[created++];}
void GObj_AddUserData(GOBJ *g,int kind,void (*fn)(void *),void *data){g->userdata=data;}
void GObj_AddProc(GOBJ *g,void (*fn)(GOBJ *),int priority){assert(priority==4 || priority==14);}
void Fighter_GiveDamage(FighterData *f,float damage){f->percent+=damage;}
int MEX_GetFtItemID(GOBJ *owner,int slot){assert(owner==fighters[0][0] && slot==0);return 237;}
'''
MAIN=r'''
static void attack(FighterData *f,int kind,int instance){f->atk_kind=kind;*(u16 *)((u8 *)f+0x206C)=instance;}
static void contact(FighterData *victim,GOBJ *source,int shield){
    if(shield){victim->shield.dmg_taken2=2;victim->shield.dmg_source=source;}
    else {victim->dmg.percent_temp=1;victim->dmg.hit_log.source=source;}
    Contact_Observe(0);memset(&victim->shield,0,sizeof(victim->shield));memset(&victim->dmg,0,sizeof(victim->dmg));
}
int main(void){
    FighterData f[3]={0};FtData data={(void *)1};
    GOBJ g[3]={{4,&f[0]},{4,&f[1]},{4,&f[2]}};
    ItemData item={238};GOBJ shot={6,&item};int i;
    fighters[0][0]=&g[0];fighters[1][0]=&g[1];fighters[1][1]=&g[2];
    for(i=0;i<3;i++){f[i].kind=i?18:27;f[i].state_id=14;f[i].ftData=&data;}
    Poison_Load(&f[0],&g[0]);Poison_Load(&f[0],&g[0]);assert(created==2);
    Poison_Frame(0);
    contact(&f[1],&shot,0);assert(poison[2].stacks==0); // unrelated item
    item.kind=237;
    for(i=0;i<6;i++)contact(&f[1],&shot,0);
    assert(poison[2].stacks==4); // cap, also works when the dart has been reflected
    for(i=0;i<120;i++)Poison_Frame(0);
    assert(f[1].percent==0); // no idle clock
    attack(&f[1],18,1);Poison_Frame(0);assert(f[1].percent==1);
    f[1].action_id=101;Poison_Frame(0);assert(f[1].percent==1); // special continuation
    attack(&f[1],1,2);Poison_Frame(0);assert(f[1].percent==1); // movement/defense
    attack(&f[1],2,3);Poison_Frame(0);assert(f[1].percent==2); // a fresh ordinary attack
    contact(&f[0],&g[1],1);assert(poison[2].stacks==4); // shield is not body contact
    contact(&f[0],&g[1],0);assert(poison[2].stacks==3); // any opponent, even after a trade
    f[0].action_id=100;f[0].state.frame=4;
    contact(&f[1],&g[0],0);assert(poison[2].stacks==4); // source move interval
    contact(&f[0],&g[1],0);f[0].state.frame=6;
    contact(&f[1],&g[0],0);assert(poison[2].stacks==3); // outside interval
    contact(&f[2],&shot,0);attack(&f[2],13,8);Poison_Frame(0);
    assert(poison[3].stacks==1 && f[2].percent==1 && f[1].percent==2); // follower has its own status
    f[1].state_id=0;Poison_Frame(0);assert(poison[2].stacks==0);
    f[1].state_id=14;attack(&f[1],18,4);Poison_Frame(0);assert(f[1].percent==2);
    contact(&f[1],&shot,0);f[1].kind=19;Poison_Frame(0);assert(poison[2].stacks==0);
    Poison_Destroy(poison_observer);assert(!poison_observer && !poison[3].stacks);
    return 0;
}
'''

def test_generated_poison_obeys_actions_contacts_and_lifecycle(tmp_path):
    vc=Path('C:/Program Files/Microsoft Visual Studio/2022/Community/VC/Auxiliary/Build/vcvars64.bat')
    cc=shutil.which('cc') or shutil.which('gcc')
    if not (vc.is_file() or cc):pytest.skip('requires host C compiler')
    mine=dict(source=[],load=[],provides=[],numbers={})
    ctx=dict(action={'SpecialN':100},moves={'game_specialn':dict(hitboxes=[dict(first=3,last=5,special_effect='Poison')])})
    game=dict(status_effect_rules={'Poison':POISON},projectiles={'dart':{'hit':{'special_effect':'Poison'}}})
    mine=own_poison.carry(mine,ctx,game,{'SpecialN':'xxxspecialn'},{0:'dart'})
    (tmp_path/'poison.c').write_text(HEADER+'\n'.join(mine['source'])+MAIN)
    if vc.is_file():
        batch=tmp_path/'run.cmd'
        batch.write_text('@echo off\ncall "'+str(vc)+'" >nul\nif errorlevel 1 exit /b 1\n'
            'cl /nologo /TC /std:c11 poison.c /Fe:poison.exe\nif errorlevel 1 exit /b 1\n'
            'poison.exe\nexit /b %errorlevel%\n')
        result=subprocess.run([os.environ['COMSPEC'],'/d','/c',str(batch)],cwd=tmp_path,capture_output=True,text=True,timeout=45)
    else:
        exe=tmp_path/'poison'
        result=subprocess.run([cc,'-std=c11',str(tmp_path/'poison.c'),'-o',str(exe)],capture_output=True,text=True,timeout=30)
        assert result.returncode==0,result.stdout+result.stderr
        result=subprocess.run([str(exe)],capture_output=True,text=True,timeout=10)
    assert result.returncode==0,result.stdout+result.stderr
