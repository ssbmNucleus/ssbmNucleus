import copy
import json
from types import SimpleNamespace
import pytest
from echo_rivals2.gamedata import article
from fighter_port import own_rivals_articles as native
from fighter_port.own_kit import ITEM_LOST
from host_c import compile_and_run


def fixture():
    def velocity(x, y, kind='SetVelocity'):
        return dict(Velocity=dict(X=x,Y=y), HorizontalVelocityType=kind, VerticalVelocityType=kind,
                    ApplyVelocityOnWindowFrame=0, ApplyVelocityUntilFrame=9999, VelocityModifiers=[])
    def phase(name, length, next_name, velocities, hits=()):
        return dict(StringTableKey=name,WindowLengthFrames=length,NextWindowStringTableKey=next_name,
            VelocityData=velocities, HitboxWindows=list(hits), bRefreshHasHit=True,
            AdvancedProperties=dict(Gravity=1,MaxFallSpeed=40,FrictionAir=0))
    hit=dict(Name='Shot',Radius=30,OnHitPropertiesName='Weak',BoneName='Root',Offset=dict(X=0,Y=0,Z=0))
    props=dict(Name='Weak',Damage=5,BaseKnockback=10,KnockbackScaling=.1,KnockbackAngle=50)
    source=dict(Windows=[phase('Launch',3,'Travel',[velocity(20,30)]),
        phase('Travel',2,'Destroy',[velocity(2,2,'MultiplyVelocity')],
              [dict(HitboxName='Shot',StartFrame=0,LengthInFrames=2)]),
        phase('Grabbed',60,'Grabbed',[velocity(0,0)],[]),phase('Destroy',8,'',[])],
        HitboxAttributes=[hit],HitboxOnHitProperties=[props], bIsProjectile=True,
        GroundCollisionResponse='::Destroy',WallCollisionResponse='::Destroy',CeilingCollisionResponse='::Destroy',
        HasHitReaction='::Destroy')
    pak=SimpleNamespace(default=lambda pkg:source)
    return article(pak,'Test/Shot',SimpleNamespace(unit=.1)),source


def test_reader_keeps_phase_graph_hit_names_velocity_kinds_and_source_without_aliasing():
    data,source=fixture()
    phases=data['program']['phases']
    assert [p['name'] for p in phases]==['Launch','Travel','Grabbed','Destroy']
    assert phases[0]['velocities'][0]['values']==[2,3]
    assert phases[1]['velocities'][0]['values']==[2,2]  # Factors are not length-scaled.
    assert phases[1]['hits'][0]['name']=='Shot' and phases[1]['hits'][0]['hit']['damage']==5
    assert phases[2]['next']=='Grabbed'
    assert json.loads(json.dumps(data))==data
    source['Windows'][0]['VelocityData'][0]['Velocity']['X']=999
    assert phases[0]['source']['VelocityData'][0]['Velocity']['X']==20
    assert data['program']['source']['Windows'][0]['VelocityData'][0]['Velocity']['X']==20
    assert [p['name'] for p in native.plan(data,'Launch')[0]]==['Launch','Travel']


HEADER=r'''
#include <assert.h>
#include <math.h>
#include <stdbool.h>
#define __attribute__(x)
typedef struct {float X,Y,Z;} Vec;
typedef struct {int state,is_hitlag;float facing_direction;Vec self_vel;int item_var[128];} ItemData;
typedef struct {void *userdata;} GOBJ;
struct ItemState {int state;int (*animCallback)(GOBJ *);void (*physCallback)(GOBJ *);int (*collCallback)(GOBJ *);};
static int dead,touch,resets;
int Lost(GOBJ *g){return dead;}
void Item_SetAirborne(ItemData *id){}
void Item_ResetAllHitPlayers(ItemData *id){resets++;}
void ItemStateChange(GOBJ *g,int state,int flags){((ItemData *)g->userdata)->state=state;}
int Item_CollAir_NoCB(GOBJ *g){return touch;}
void Item_ReflectVelocity(GOBJ *g){ItemData *id=g->userdata;id->facing_direction=-id->facing_direction;
    id->self_vel.X*=-1.5f;id->self_vel.Y*=1.5f;}
'''


def test_native_phase_velocity_hitlag_contact_reflection_and_cleanup(tmp_path):
    data,_=fixture()
    item,receipt=native.build(data,'shot',{},1,entry='Launch')
    source=item['code'].replace('#include "../mex.h"','').replace(ITEM_LOST,'')
    assert len(item['states'])==3 and len(item['states'][2])==1
    assert receipt['phases']==['Launch','Travel']
    compile_and_run(tmp_path,HEADER+source+r'''
int main(void){
    ItemData id={0};GOBJ g={&id};RivalsArticle *p=RA_Data(&g);
    p->ready=1;id.facing_direction=-1;
    assert(!RA_Anim(&g) && id.state==1 && resets==1);
    RA_Phys(&g);assert(id.self_vel.X==-2 && id.self_vel.Y==3);
    assert(!RA_Anim(&g));RA_Phys(&g);assert(fabsf(id.self_vel.Y-2.9f)<.0001f);
    id.is_hitlag=1;assert(!RA_Anim(&g));RA_Phys(&g);
    assert(p->frame==1 && fabsf(id.self_vel.Y-2.9f)<.0001f);
    id.is_hitlag=0;assert(!RA_Anim(&g));RA_Phys(&g);
    assert(!RA_Anim(&g) && id.state==2 && p->frame==0 && resets==2);
    RA_Phys(&g);assert(id.self_vel.X==-4 && fabsf(id.self_vel.Y-5.4f)<.0001f);
    assert(!OnReflect(&g) && id.self_vel.X==6 && p->facing==1 && p->speed==1.5f);
    assert(OnGiveDamage(&g) && OnHitShieldDetermineDestroy(&g));
    touch=1;assert(RA_Coll(&g));touch=0;assert(!RA_Coll(&g));
    assert(!RA_Anim(&g));RA_Phys(&g);assert(id.self_vel.X==6); // Multiply is an impulse.
    assert(RA_Anim(&g));dead=1;assert(RA_Anim(&g));
    return 0;
}
''')


def test_unknown_behavior_rejects_whole_article_and_loops_are_bounded():
    data,_=fixture()
    data['program']['phases'][1]['next']='Launch'
    assert native.plan(data,'Launch')[1]
    item,receipt=native.build(data,'shot',{},1,entry='Launch',max_life=100)
    assert receipt['loop'] and receipt['max_life']==100
    data['program']['phases'][1]['next']='Missing'
    with pytest.raises(native.Unsupported,match='missing'):native.build(data,'shot',{},1,entry='Launch')
    data,_=fixture();data['program']['phases'][0]['velocities'][0]['modifiers']=[dict(name='Custom')]
    with pytest.raises(native.Unsupported,match='modifier'):native.build(data,'shot',{},1,entry='Launch')
    data,_=fixture();data['ends']['GroundCollisionResponse']='Custom'
    with pytest.raises(native.Unsupported,match='requires an adapter'):native.build(data,'shot',{},1,entry='Launch')
    data,_=fixture();data['program']['phases'][1]['refresh']=False
    with pytest.raises(native.Unsupported,match='hit memory'):native.build(data,'shot',{},1,entry='Launch')
    data,_=fixture();data['class']="Class'UnknownSeekingProjectile'"
    with pytest.raises(native.Unsupported,match='compiled article class'):native.build(data,'shot',{},1,entry='Launch')


def test_continuous_hit_survives_phase_change_and_loop_without_rehit(tmp_path):
    data,_=fixture();phases=data['program']['phases']
    phases[0]['hits']=copy.deepcopy(phases[1]['hits'])
    phases[0]['hits'][0]['length']=60
    phases[1]['hits'][0]['length']=60
    phases[1]['refresh']=False;phases[1]['next']='Travel'
    item,receipt=native.build(data,'shot',{},1,entry='Launch',max_life=10)
    assert item['states'][2]==[] and receipt['loop']
    source=item['code'].replace('#include "../mex.h"','').replace(ITEM_LOST,'')
    compile_and_run(tmp_path,HEADER+source+r'''
int main(void){
    ItemData id={0};GOBJ g={&id};RivalsArticle *p=RA_Data(&g);
    p->ready=1;id.facing_direction=1;assert(!RA_Anim(&g));
    assert(resets==1);for(int i=0;i<3;i++)assert(!RA_Anim(&g));
    assert(id.state==2 && resets==1);
    for(int i=0;i<6;i++)assert(!RA_Anim(&g));
    assert(id.state==2 && resets==1 && RA_Anim(&g));
    return 0;
}
''')


def test_article_compiles_with_real_native_kit_and_item_script_fields():
    import os
    from fighter_port import code, states, own_template
    from test_own_template import a_ctx, donor_rows
    from vault.echo import subactions
    data,_=fixture();item,_=native.build(data,'shot',{},1,entry='Launch')
    fields={p.key for p in subactions.COMMANDS[0x0b].params}
    assert set(item['states'][2][0][1]) <= fields|{'again','group'}
    kit=code.toolkit(os.environ.get('MEXTK_DIR'))
    if kit is None:pytest.skip('requires MexTK')
    compiler=pytest.importorskip('vault.echo.tier2.build')
    built,why=own_template.build(a_ctx());assert why is None
    built['items']=[item]
    rows=donor_rows();built['table']=states.table_text(rows,built['rows'])
    files,_=code.source('Marth',own=built,onload=0x801364AC,state_rows=(rows,built['rows']))
    checked=compiler.check_files(files,mextk_dir=str(kit))
    assert checked.get('ok'),checked.get('error')
