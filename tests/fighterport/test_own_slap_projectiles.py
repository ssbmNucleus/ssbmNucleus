import pytest
from fighter_port import own_slap_projectiles as projectiles, own_slap_motion as motion
from fighter_port.own_kit import fill
from fighter_port.own_slap_expr import Unsupported
from host_c import compile_and_run

def test_generated_projectile_contact_lifetime_and_distance(tmp_path):
    header=r'''
#include <assert.h>
#include <math.h>
#include <stdbool.h>
#define __attribute__(x)
typedef struct {float X,Y,Z;} Vec3;
typedef struct {int state;float facing_direction;Vec3 pos,self_vel;int item_var[128];} ItemData;
typedef struct {Vec3 rot;} JOBJ;
typedef struct {void *userdata;JOBJ *hsd_object;} GOBJ;
struct ItemState {int state;int (*animCallback)(GOBJ *);void (*physCallback)(GOBJ *);int (*collCallback)(GOBJ *);};
static int dead,touch,reflected,cleared;
int Lost(GOBJ *g){return dead;}
void Item_SetAirborne(ItemData *id){}
void Item_ResetAllHitPlayers(ItemData *id){cleared++;}
void ItemStateChange(GOBJ *g,int state,int flags){((ItemData *)g->userdata)->state=state;}
int Item_CollAir_NoCB(GOBJ *g){return touch;}
void Item_ReflectVelocity(GOBJ *g){reflected++;}
void JOBJ_SetMtxDirtySub(JOBJ *j){}
'''
    source=fill(projectiles.ITEM,dict(storage=projectiles.STORAGE,hits=2,bounces=2,life=90,distance='20.0f',collision=15,
        physics='id->self_vel.X+=p->gx;id->self_vel.Y+=p->gy;',bounce_keep='1.0f',bounce_cos='0.71f'))
    source=source.replace('#include "../mex.h"','')
    compile_and_run(tmp_path,header+source+r'''
int main(void){
    ItemData id={0};JOBJ model={0};GOBJ g={&id,&model};PortProjectile *p=PP_Data(&g);
    p->ready=1;p->gx=.1f;p->gy=-.2f;id.self_vel.X=2;id.self_vel.Y=3;
    assert(!Projectile_Anim(&g) && id.state==1 && cleared==1);
    assert(id.self_vel.X==2 && id.self_vel.Y==3);
    Projectile_Phys(&g);assert(fabsf(id.self_vel.X-2.1f)<.0001f);
    assert(fabsf(id.self_vel.Y-2.8f)<.0001f);
    assert(!OnGiveDamage(&g) && OnGiveDamage(&g));
    assert(OnHitShieldDetermineDestroy(&g) && !OnReflect(&g) && reflected==1);
    id.self_vel.X=5;id.self_vel.Y=-2;touch=1;assert(!Projectile_Coll(&g));
    assert(p->bounces==1 && id.self_vel.Y>0);
    assert(!Projectile_Coll(&g) && p->bounces==1); // Continuous contact is one bounce.
    touch=0;assert(!Projectile_Coll(&g));touch=4;assert(Projectile_Coll(&g));
    p->age=89;assert(Projectile_Anim(&g));
    p->age=0;id.pos.X=21;assert(Projectile_Anim(&g));
    p->distance=0;id.pos.X=p->last_x;dead=1;assert(Projectile_Anim(&g));
    return 0;
}
''')


def fixture():
    data=dict(atkprop=dict(dmg=5,angle=65,basekb=100,kbgain=2,setkb=0),hitSize=.8,
              gravity=[0,-80],move_vel=[20,0],deactivateAfterHits=1,deactivateAfterBounces=2)
    game=dict(unit=5,kb=dict(base=.4,gain=30),projectiles={'shot':data},
              article_models={'shot':dict(folder='shot')},moves={'game_specialn':dict(slapcity_move='spn',
              articles=[dict(id='shot',bank='projectiles',bone='hand',offset=[0,1,0],world=[2,0,0])])})
    return projectiles.Builder(dict(source_game=game,drawn=.5,joints={'hand':9}))


def test_source_spawn_velocity_is_world_space_and_specs_reuse_models():
    builder=fixture();compiler=motion.Compiler(builder)
    node=dict(t='SASA',id='shot',b='projectiles',g=dict(md=[dict(i='Velocity',o=dict(t='OSV2',
        x=dict(t='FSM',a='x_vel_raw'),y=dict(f=-30)))]))
    source=builder.spawn(node,'spn',compiler)
    assert 'PP_Spawn(gobj,0, 9, 0.0f, 0.5f, 0.0f, 1.0f' in source
    assert '((r->x * r->facing))*PM_SPEED' in source
    assert source.count('r->facing')==1
    builder.spawn(node,'spn',compiler)
    assert len(builder.items)==1 and builder.items[0]['model']['folder']=='shot'
    hit=builder.items[0]['states'][1][0][1]
    assert hit['damage']==5 and hit['size']==512 and hit['base_knockback']==40
    assert hit['knockback_growth']==60


def test_unsupported_initializer_never_builds_a_partially_configured_projectile():
    builder=fixture();compiler=motion.Compiler(builder)
    node=dict(t='SASA',id='shot',b='projectiles',g=dict(md=[dict(i='Mystery')]))
    with pytest.raises(Unsupported,match='initializer Mystery'):
        builder.spawn(node,'spn',compiler)
    assert not builder.items


@pytest.mark.parametrize('speed',[3,-3])
def test_returning_family_reverses_and_accelerates_from_source_parameters(tmp_path,speed):
    source=fill(projectiles.RETURNING,dict(turn_start='0.1f',turn_duration='0.3f',speed=f'{speed}.0f',lift='1.0f'))
    compile_and_run(tmp_path,r'''
#include <assert.h>
typedef struct {float travel,return_gain;} PortProjectile;
typedef struct {struct {float X,Y;} self_vel;} ItemData;
void physics(ItemData *id,PortProjectile *p){
'''+source+r'''
}
int main(void){
    PortProjectile p={0};ItemData id={0};p.return_gain=1;
    physics(&id,&p);assert(id.self_vel.X==SPEED && id.self_vel.Y==0);
    p.travel=.24f;physics(&id,&p);assert(id.self_vel.X*SPEED<0 && id.self_vel.Y==1);
    p.travel=.41f;physics(&id,&p);assert(id.self_vel.X*SPEED<-9 && id.self_vel.Y==0);
    return 0;
}
'''.replace('SPEED',str(speed)))
