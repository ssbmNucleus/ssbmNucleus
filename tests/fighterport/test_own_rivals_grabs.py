from copy import deepcopy
import re
import pytest
from fighter_port import own_rivals_grabs as grabs, own_rivals_states, own_template
from echo_rivals2.branches import branch_stem
from host_c import compile_and_run
from test_own_template import a_ctx, DONOR_ACTIONS

# the native command grab's engine, mocked for the host compiler
HEADER=r'''
#include <assert.h>
#include <stdint.h>
typedef unsigned char u8;
typedef struct GOBJ GOBJ;
typedef struct {char wire[128];int active,x4,dmg,angle,kb_growth,kb,wdsk,attribute,shield_dmg,hitsound_severity,hitsound_kind,x40,x41;
float dmg_f,size;void *bone;struct {float X,Y,Z;} offset;} ftHit;
typedef struct {int ply,state_id;struct {int dead,sleep,hitbox_active;} flags;
struct {GOBJ *attacker;} grab;struct {intptr_t state_var7;} state_var;
struct {void *joint;} bones[2];ftHit hitbox[4],throw_hitbox[2];
struct {int air_state;struct {float X,Y;} self_vel,self_vel_ground;} phys;
struct {float dash_initial_velocity;} attr;
struct {struct {float X;} lstick;} input;
float facing_direction,percent;} FighterData;
struct GOBJ {FighterData *userdata;};
static GOBJ *players[6];static int t_frame[6],released,pulled,knocked,land,landing,init_grab;
#define ASID_CAPTUREPULLEDHI 223
#define ASID_CAPTUREPULLEDLW 226
#define ST_S 375
#define ST_S_AIR 376
GOBJ *Fighter_GetSubcharGObj(int p,int s){return s?0:players[p];}
void MockPullOwner(GOBJ *g){pulled++;}
void MockPullTarget(GOBJ *g,GOBJ *owner){g->userdata->grab.attacker=owner;g->userdata->state_id=ASID_CAPTUREPULLEDHI;}
void MockNew(FighterData *f,ftHit *h){}
void MockDamage(ftHit *h,int damage,GOBJ *g){h->dmg=h->dmg_f=damage;}
void MockAngle(ftHit *h,int angle,GOBJ *g){h->angle=angle;}
void MockPlace(FighterData *f,ftHit *h){}
void MockAfter(FighterData *f){}
void ActionStateChange(float a,int b,int c,GOBJ *g,int state,int flags,int d){g->userdata->state_id=state;}
void Fighter_AdvanceScript(GOBJ *g){}
void Fighter_SetAirborne(FighterData *f){f->phys.air_state=1;}
void Fighter_SetGrounded2(FighterData *f){f->phys.air_state=0;}
void Fighter_BreakGrab(GOBJ *owner,GOBJ *victim){owner->userdata->grab.attacker=victim->userdata->grab.attacker=0;}
void Fighter_ThrownRelease_UpdateUnk(GOBJ *owner,GOBJ *victim){released++;victim->userdata->percent+=owner->userdata->throw_hitbox[0].dmg_f;Fighter_BreakGrab(owner,victim);}
void Fighter_ThrownApplyKnockback(GOBJ *victim,GOBJ *owner,int top){knocked++;victim->userdata->state_id=75;}
void Fighter_EnterFall(GOBJ *g){g->userdata->state_id=29;}
void Enter(GOBJ *g,int state){g->userdata->state_id=state;t_frame[g->userdata->ply]=1;}
int Tick(GOBJ *g){return ++t_frame[g->userdata->ply];}
void Leave(GOBJ *g,int helpless,int lag){g->userdata->state_id=g->userdata->phys.air_state?29:14;}
void Fighter_InitGrab(FighterData *f,int mode,void *owner,void *item,void *victim){init_grab++;}
void Fighter_HitboxDisableAll(GOBJ *g){for(int i=0;i<4;i++)g->userdata->hitbox[i].active=0;}
void Fighter_PhysAir_ApplyGravityFastfall(GOBJ *g){g->userdata->phys.self_vel.Y-=.06f;}
void Fighter_EnterSpecialLanding(GOBJ *g,int a,float lag){landing=(int)lag;Enter(g,43);}
int Fighter_CollAir_IgnoreLedge_NoCB(GOBJ *g){return land;}
void Fighter_CollAir_GrabFacingLedgeWalljump(GOBJ *g,int a,void (*onland)(GOBJ *)){if(land)onland(g);}
void Fighter_SetBoneRotY(FighterData *f,int bone,float angle){}
'''


def fixture():
    event=dict(window='Active',first=5,last=8,condition=dict(WindowCancelType='::OnGrab',
        PostCancelWindowStringTableKey='Hold',WindowCancelPrerequisite='::None'))
    catch=dict(cmd='CATCH',real=5,from_bone='head',args=[0,'top',3,0,10,5,0,10,5,0,None])
    launch=dict(rivals2_attack='Fspecial',windows=[(1,'Startup',4),(5,'Active',4),(9,'Recovery',6)],
                end=15,window_cancels=[event],other=[catch],catch_end=9,hitboxes=[])
    hold=dict(rivals2_attack='Fspecial',windows=[(1,'Hold',3),(4,'Release',4)],
              end=8,window_cancels=[],other=[],hitboxes=[],conditional_only=True)
    attack=dict(Windows=[dict(StringTableKey='Startup',WindowLengthFrames=4,NextWindowStringTableKey='Active'),
                         dict(StringTableKey='Active',WindowLengthFrames=4,NextWindowStringTableKey='Recovery'),
                         dict(StringTableKey='Recovery',WindowLengthFrames=6),
                         dict(StringTableKey='Hold',WindowLengthFrames=3,NextWindowStringTableKey='Release'),
                         dict(StringTableKey='Release',WindowLengthFrames=4)],
                ThrowData=dict(ThrowReleaseData=[dict(ReleaseWindowStringTableKey='Release',
                    ThrowKnockbackData=dict(Damage=12,BaseKnockback=8.,KnockbackScaling=.25,KnockbackAngle=270))]))
    moves=dict(game_specials=launch,game_specialairs=deepcopy(launch))
    for name in ('Fspecial','FspecialAir'):
        moves['game_'+branch_stem(name,'Hold')[3:]]=deepcopy(hold)
    game=dict(game='rivals2',moves=moves,source_attacks={'Fspecial':attack})
    return game,launch,hold


def split_fixture():
    game,launch,hold=fixture()
    hold.update(windows=[(1,'Hold',3)],end=4,path_end='Release')
    for name in ('Fspecial','FspecialAir'):
        game['moves']['game_'+branch_stem(name,'Hold')[3:]]=deepcopy(hold)
        game['moves']['game_'+branch_stem(name,'Release')[3:]]=dict(rivals2_attack='Fspecial',
            windows=[(1,'Release',4)],end=5,window_cancels=[],other=[],hitboxes=[],conditional_only=True)
    return game,launch,hold


def test_declaration_rejects_unknown_or_conditional_capture_instead_of_allocating_it():
    game,launch,hold=fixture();event=launch['window_cancels'][0]
    assert grabs.declaration(game,launch,event)['release']==4
    planned=own_rivals_states.plan(game)
    assert len(planned['clips'])==2 and not planned['limits']
    assert len(planned['nodes']['specials']['captures'])==1
    assert not planned['nodes']['specials']['branches'] # Contact is established by native collision, not proximity.
    game['source_attacks']['Fspecial']['ThrowData']={}
    planned=own_rivals_states.plan(game)
    assert not planned['clips'] and any('throw release' in limit for limit in planned['limits'])


def test_native_grab_window_capture_release_once_hitlag_and_safe_interruption(tmp_path):
    game,launch,hold=fixture()
    rows=[dict(flags=0x340212),dict(flags=0x340612)]*2
    bindings=[(375,300,launch,False),(376,301,deepcopy(launch),False),
              (377,302,hold,False),(378,303,deepcopy(hold),False)]
    source,receipt=grabs.build(dict(first=375,drawn=1,joints={'head':1},source_game=game),rows,bindings)
    assert len(receipt['carried'])==2 and not receipt['limits']
    names=dict(NG_PULL_OWNER='MockPullOwner',NG_PULL_TARGET='MockPullTarget',NG_HIT_NEW='MockNew',
        NG_HIT_DAMAGE='MockDamage',NG_HIT_ANGLE='MockAngle',NG_HIT_PLACE='MockPlace',NG_HIT_AFTER='MockAfter')
    source=re.sub(r'#define (NG_\w+) [^\n]+',lambda m:'#define '+m[1]+' '+names[m[1]],source)
    header=HEADER.replace('int dead,sleep,hitbox_active;', 'int dead,sleep,hitbox_active,hitlag;')
    header+=r'''
static int checked_input,physics,collision;
void RV_Anim(GOBJ *g){Tick(g);}
void RV_IASA(GOBJ *g){checked_input++;}
void RV_Phys(GOBJ *g){physics++;g->userdata->phys.self_vel.Y=-1;}
void RV_Coll(GOBJ *g){collision++;}
'''
    compile_and_run(tmp_path,header+source+r'''
int main(void){
FighterData f={0},t={0};GOBJ owner={&f},victim={&t};players[0]=&owner;players[1]=&victim;
f.facing_direction=1;f.bones[1].joint=&owner;t.state_id=14;
RG_Load(&f);Enter(&owner,375);RG_Enter(&owner);assert(init_grab==1);
t_frame[0]=3;RG_Anim(&owner);assert(!f.hitbox[0].active);
RG_Anim(&owner);assert(f.hitbox[0].active && f.hitbox[0].attribute==8 && f.hitbox[0].dmg==0);
assert(t.state_id==14); // Only real collision invokes these endpoints in the game.
t_frame[0]=8;RG_Anim(&owner);assert(!f.hitbox[0].active);
Enter(&owner,376);RG_Enter(&owner);f.grab.attacker=&victim;
RG_Caught(&owner);NativeGrab_Victim(&victim,&owner);
assert(f.state_id==378 && t.phys.air_state && rg_state[0].holding);
RG_IASA(&owner);RG_Phys(&owner);RG_Coll(&owner);
assert(!checked_input && physics==1 && !collision && f.phys.self_vel.Y==0);
t_frame[0]=2;RG_Anim(&owner);assert(released==0);
f.flags.hitlag=1;RG_Anim(&owner);assert(t_frame[0]==3 && released==0);
f.flags.hitlag=0;RG_Anim(&owner);
assert(released==1 && knocked==1 && t.percent==12 && t.state_id==75 && !rg_state[0].holding);
assert(f.throw_hitbox[0].angle==270);
RG_Anim(&owner);assert(released==1);RG_IASA(&owner);assert(checked_input==1);
Enter(&owner,375);RG_Enter(&owner);f.grab.attacker=&victim;RG_Caught(&owner);NativeGrab_Victim(&victim,&owner);
f.state_id=75;RG_Frame(&f,&owner);assert(t.state_id==29 && !t.grab.attacker && !rg_state[0].active);
Enter(&owner,375);RG_Enter(&owner);f.grab.attacker=&victim;RG_Caught(&owner);NativeGrab_Victim(&victim,&owner);
f.state_id=75;t.state_id=75;RG_Frame(&f,&owner);assert(t.state_id==75); // External damage is authoritative.
return 0;}
''')


def test_whole_generated_grab_module_compiles_with_native_kit():
    import os
    from pathlib import Path
    from fighter_port import code, states
    from test_own_template import donor_rows
    kit=code.toolkit(os.environ.get('MEXTK_DIR') or str(Path.home() / 'projects' / 'm-ex' / 'MexTK'))
    if kit is None:pytest.skip('requires MexTK')
    compiler=pytest.importorskip('vault.echo.tier2.build')
    game,launch,hold=split_fixture()
    ctx=a_ctx(source_game=game,generic_specials=True,moves=game['moves'],drawn=1,joints={'head':1},
              action={name:295+i for i,name in enumerate(DONOR_ACTIONS)},
              total={name:40 for name in DONOR_ACTIONS})
    built,why=own_template.build(ctx)
    assert why is None and len(built['numbers']['grabs']['carried'])==2
    assert all(r['release_frame']==1 and r['release_state']!=r['capture_state'] for r in built['numbers']['grabs']['carried'])
    assert not built['numbers']['transitions']['limits']
    assert 'RG_Load(fd);' in built['load'] and 'RG_Frame(fd,gobj);' in built['frame']
    rows=donor_rows();built['table']=states.table_text(rows,built['rows'])
    files,_=code.source('Marth',own=built,onload=0x801364AC,state_rows=(rows,built['rows']))
    checked=compiler.check_files(files,mextk_dir=str(kit))
    assert checked.get('ok'),checked.get('error')


def test_each_exported_clip_normalizes_its_grab_with_its_own_pose(monkeypatch):
    import numpy as np
    from echo_rivals2 import gamedata
    from test_rivals2_reader import win
    hit=dict(grab=True,id=0,bone='head',size=3,x=0,y=0,z=0,first=1,last=3)
    monkeypatch.setattr(gamedata,'hitbox_rows',lambda *args:[dict(hit)])
    class Reader:
        def pose(self,clip,frame):
            root=np.eye(4);root[0,3]=1
            head=np.eye(4);head[:3,3]=[10,20,30] if clip=='air' else [2,3,4]
            return dict(Trans=root,head=head)
    attack=dict(Windows=[win('Active',3)])
    outputs=[]
    for clip,stem in [('ground','d01specials'),('air','d01specialairs')]:
        part=gamedata.Part(attack,gamedata.path_from(attack,'Active'),stem)
        entry=gamedata.entry_of(Reader(),attack,part,clip,'fixture','Fspecial')
        catch=entry['other'][0]
        assert catch['args'][1]=='top' and catch['from_bone']=='head'
        outputs.append(catch['args'][3:6])
    assert outputs==[[1,3,4],[9,20,30]]


def test_reader_splits_explicit_capture_at_release_without_shortening_the_motion():
    from echo_rivals2 import gamedata
    from test_rivals2_reader import win
    event=dict(WindowCancelType='::OnGrab',PostCancelWindowStringTableKey='Hold')
    attack=dict(Windows=[win('Startup',10,'Whiff',WindowCancels=[event]),win('Whiff',20),
        win('Hold',30,'Release'),win('Release',1,'Recovery'),win('Recovery',43)],
        ThrowData=dict(ThrowReleaseData=[dict(ReleaseWindowStringTableKey='Release')]))
    parts=gamedata.parts_with_branches('Fspecial',attack,[('main','d01specials')])
    assert [name for name,_ in parts]==['main','Hold','Release']
    before=gamedata.path_from(attack,'Hold',stops={'Hold','Release'})
    after=gamedata.path_from(attack,'Release',stops={'Hold','Release'})
    assert [w['StringTableKey'] for w in before]==['Hold']
    assert sum(w['WindowLengthFrames'] for w in before+after)==74
    planned=own_rivals_states.plan(split_fixture()[0])
    assert len(planned['clips'])==4 and not planned['limits']
    assert planned['nodes'][branch_stem('Fspecial','Hold')[3:]]['loop'][0]==branch_stem('Fspecial','Release')[3:]


def test_split_release_keeps_capture_until_declared_throw_phase(tmp_path):
    game,launch,hold=split_fixture()
    release=game['moves']['game_'+branch_stem('Fspecial','Release')[3:]]
    rows=[dict(flags=0x340212),dict(flags=0x340612)]*3
    bindings=[(375,300,launch,False),(376,301,deepcopy(launch),False),
              (377,302,hold,False),(378,303,deepcopy(hold),False),
              (379,304,release,False),(380,305,deepcopy(release),False)]
    source,_=grabs.build(dict(first=375,drawn=1,joints={'head':1},source_game=game),rows,bindings)
    names=dict(NG_PULL_OWNER='MockPullOwner',NG_PULL_TARGET='MockPullTarget',NG_HIT_NEW='MockNew',
        NG_HIT_DAMAGE='MockDamage',NG_HIT_ANGLE='MockAngle',NG_HIT_PLACE='MockPlace',NG_HIT_AFTER='MockAfter')
    source=re.sub(r'#define (NG_\w+) [^\n]+',lambda m:'#define '+m[1]+' '+names[m[1]],source)
    header=HEADER.replace('int dead,sleep,hitbox_active;', 'int dead,sleep,hitbox_active,hitlag;')
    header+=r'''
void RV_Anim(GOBJ *g){if(Tick(g)>=4 && g->userdata->state_id==377)Enter(g,379);}
void RV_IASA(GOBJ *g){}
void RV_Phys(GOBJ *g){}
void RV_Coll(GOBJ *g){}
'''
    compile_and_run(tmp_path,header+source+r'''
int main(void){
FighterData f={0},t={0};GOBJ owner={&f},victim={&t};players[0]=&owner;players[1]=&victim;
f.bones[1].joint=&owner;RG_Load(&f);Enter(&owner,375);RG_Enter(&owner);
f.grab.attacker=&victim;RG_Caught(&owner);NativeGrab_Victim(&victim,&owner);
t_frame[0]=2;RG_Anim(&owner);assert(!released && rg_state[0].holding);
RG_Anim(&owner);assert(f.state_id==379 && t_frame[0]==1 && released==1 && t.percent==12);
assert(t.state_id==75 && !rg_state[0].holding); // Release damages instead of dropping on phase change.
RG_Anim(&owner);assert(released==1);return 0;}
''')
