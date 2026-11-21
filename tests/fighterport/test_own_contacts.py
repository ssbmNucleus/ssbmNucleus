"""The generated observer sees trades, armor, shields and secondary opponents before reset."""
from pathlib import Path
import os,shutil,subprocess
import pytest
from fighter_port import own_contacts as contacts,code

HEADER='''#include <assert.h>
#include <string.h>
typedef struct GOBJ GOBJ;
typedef struct {int ply,kind;struct {int sleep;} flags;
struct {float percent_temp,tip_force_applied;struct {GOBJ *source;float force_applied;} hit_log;} dmg;
struct {int dmg_taken2;GOBJ *dmg_source;} shield;} FighterData;
struct GOBJ {void *userdata;};
#define FTPRI_DMGAPPLY 14
static GOBJ *fighters[6][2],helper;
static void (*observe)(GOBJ *);
static void (*destroy)(void *);
static int creates,registers,hit_count,hurt_count,shield_count;
static float hit_damage,hurt_damage;
GOBJ *Fighter_GetGObj(int p){return fighters[p][0];}
GOBJ *Fighter_GetSubcharGObj(int p,int sub){return fighters[p][sub];}
GOBJ *GObj_Create(int kind,int link,int priority){assert(link==0);creates++;return &helper;}
void GObj_AddUserData(GOBJ *g,int kind,void (*fn)(void *),void *data){destroy=fn;g->userdata=data;}
void GObj_AddProc(GOBJ *g,void (*fn)(GOBJ *),int priority){assert(priority==14);observe=fn;registers++;}
'''
CALLBACKS='''
static void GotHit(GOBJ *owner,GOBJ *other,float damage,int shield){
assert(owner!=other);hit_count++;hit_damage+=damage;shield_count+=shield;}
static void GotHurt(GOBJ *owner,GOBJ *other,float damage,int shield){
assert(owner!=other);hurt_count++;hurt_damage+=damage;shield_count+=shield;}
'''
MAIN='''int main(void){
FighterData f[3]={0};GOBJ g[3]={{&f[0]},{&f[1]},{&f[2]}};
fighters[0][0]=&g[0];fighters[1][0]=&g[1];fighters[1][1]=&g[2];
f[0].kind=27;f[1].ply=f[2].ply=1;f[1].kind=f[2].kind=4;
Contact_Load(&f[0],&g[0]);Contact_Load(&f[0],&g[0]);assert(creates==1 && registers==1);
// Simultaneous body damage: outgoing and incoming callbacks both survive the trade.
f[0].dmg.percent_temp=7;f[0].dmg.hit_log.source=&g[1];f[0].dmg.hit_log.force_applied=20;
f[1].dmg.percent_temp=6;f[1].dmg.hit_log.source=&g[0];f[1].dmg.hit_log.force_applied=18;
observe(&helper);assert(hit_count==1 && hurt_count==1 && hit_damage==6 && hurt_damage==7);
// Engine consumes the pending amounts. Stale source pointers and later percent changes do not re-fire.
memset(&f[0].dmg,0,sizeof(f[0].dmg));f[1].dmg.percent_temp=0;
observe(&helper);assert(hit_count==1 && hurt_count==1);
// A follower with zero-knockback armored damage is still a body contact.
f[2].dmg.percent_temp=4;f[2].dmg.hit_log.source=&g[0];
observe(&helper);assert(hit_count==2 && hit_damage==10);
memset(&f[2].dmg,0,sizeof(f[2].dmg));
// Shields are tagged, never misreported as body damage, including an incoming shield hit.
f[1].shield.dmg_taken2=8;f[1].shield.dmg_source=&g[0];
f[0].shield.dmg_taken2=3;f[0].shield.dmg_source=&g[1];
observe(&helper);assert(hit_count==3 && hurt_count==2 && shield_count==2);
memset(&f[0].shield,0,sizeof(f[0].shield));memset(&f[1].shield,0,sizeof(f[1].shield));
// Phantom-only and sleeping records cannot mint contact events.
f[1].dmg.percent_temp=2;f[1].dmg.tip_force_applied=5;f[1].dmg.hit_log.force_applied=0;
observe(&helper);assert(hit_count==3);
f[1].dmg.tip_force_applied=0;f[1].flags.sleep=1;
observe(&helper);assert(hit_count==3);f[1].flags.sleep=0;
// Reused player slots/kinds cannot turn an old registration into a different owner.
f[0].kind=9;observe(&helper);assert(hit_count==3);f[0].kind=27;
fighters[0][0]=0;observe(&helper);assert(hit_count==3);fighters[0][0]=&g[0];
// Scene teardown clears ownership and permits one fresh helper on the next load.
destroy(helper.userdata);assert(!contact_observer && !contact_owners[0]);
observe(&helper);assert(hit_count==3);
Contact_Load(&f[0],&g[0]);assert(creates==2 && registers==2);
observe(&helper);assert(hit_count==4);
// Sub-one damage must survive staling; item-native damage counters use integers.
hit_damage=0;f[1].dmg.percent_temp=0.91f;
observe(&helper);assert(hit_count==5 && hit_damage>0.90f && hit_damage<0.92f);
return 0;}
'''

def test_actual_contact_observer_before_damage_reset(tmp_path):
    vc=Path('C:/Program Files/Microsoft Visual Studio/2022/Community/VC/Auxiliary/Build/vcvars64.bat')
    cc=shutil.which('cc') or shutil.which('gcc')
    if not (vc.is_file() or cc):pytest.skip('requires host C compiler')
    (tmp_path/'contacts.c').write_text(HEADER+'\n'.join(contacts.source('GotHit','GotHurt'))+CALLBACKS+MAIN)
    if vc.is_file():
        batch=tmp_path/'run.cmd'
        batch.write_text('@echo off\ncall "'+str(vc)+'" >nul\nif errorlevel 1 exit /b 1\n'
                         'cl /nologo /TC /std:c11 contacts.c /Fe:contacts.exe\nif errorlevel 1 exit /b 1\n'
                         'contacts.exe\nexit /b %errorlevel%\n')
        r=subprocess.run([os.environ['COMSPEC'],'/d','/c',str(batch)],cwd=tmp_path,capture_output=True,text=True,timeout=45)
    else:
        exe=tmp_path/'contacts'
        r=subprocess.run([cc,'-std=c11',str(tmp_path/'contacts.c'),'-o',str(exe)],capture_output=True,text=True,timeout=30)
        assert r.returncode==0,r.stdout+r.stderr
        r=subprocess.run([str(exe)],capture_output=True,text=True,timeout=10)
    assert r.returncode==0,r.stdout+r.stderr

def test_contact_runtime_compiles_against_native_kit(tmp_path):
    kit=code.toolkit(os.environ.get('MEXTK_DIR') or str(Path.home() / 'projects' / 'm-ex' / 'MexTK'))
    if kit is None:pytest.skip('requires MexTK')
    tier2=pytest.importorskip('vault.echo.tier2.build')
    source=contacts.source('GotHit','GotHurt')+[
        'static void GotHit(GOBJ *a,GOBJ *b,float damage,int shield){}',
        'static void GotHurt(GOBJ *a,GOBJ *b,float damage,int shield){}']
    own=dict(source=source,load=['Contact_Load(fd,gobj);'],frame=[],provides=[],table=[])
    files,_=code.source('Marth',onload=0x801364AC,own=own)
    result=tier2.check_files(files,mextk_dir=str(kit))
    assert result.get('ok'),result.get('error')

def test_contact_callback_names_are_identifiers():
    with pytest.raises(ValueError,match='C identifiers'):
        contacts.source('bad()','GotHurt')
