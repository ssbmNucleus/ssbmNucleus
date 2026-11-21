"""Run generated common movement, rather than checking only C strings."""
import pytest
from fighter_port import own_slap_motion as motion, own_slap_expr as expr
from host_c import compile_and_run


def setting(group, field, value):
    return dict(t='SASF',s=[dict(g={'t':group,'a' if group=='FSM' else 'i':field},w='Set',
                                s=value if isinstance(value,dict) else {'f':value})])


def sequence(*actions):
    return dict(t='SAOS',ac=list(actions))


HEADER=r'''
#include <assert.h>
#include <math.h>
typedef struct {int ply,state_id,action_id;float facing_direction;
struct {int hitlag;} flags;
struct {int held,held_prev,down;float trigger;struct {float X,Y;} lstick,lstick_prev,cstick;} input;
struct {int air_state;struct {float X,Y;} self_vel,self_vel_ground;} phys;
struct {float gravity,terminal_velocity,aerial_drift_stick_mult,aerial_drift_base,aerial_drift_max;} attr;
} FighterData;
typedef struct {FighterData *userdata;} GOBJ;
static int t_frame[6],land,landing,handovers,ledge;
void Fighter_SetAirborne(FighterData *f){f->phys.air_state=1;f->phys.self_vel.X=0;}
void Fighter_SetGrounded2(FighterData *f){f->phys.air_state=0;}
void Fighter_SetBoneRotY(FighterData *f,int bone,float value){}
void Fighter_PhysAir_ApplyGravity(FighterData *f,float g,float limit){f->phys.self_vel.Y=fmaxf(-limit,f->phys.self_vel.Y-g);}
void Fighter_PhysAir_ApplyAerialDrift(FighterData *f){}
void Fighter_PhysGround_ApplyFriction(GOBJ *g){}
int Fighter_CollGround_PassLedge(GOBJ *g){return 1;}
int Fighter_CollAir_IgnoreLedge_NoCB(GOBJ *g){return land;}
void Fighter_CollAir_GrabFacingLedgeWalljump(GOBJ *g,int x,void (*cb)(GOBJ *)){ledge++;if(land)cb(g);}
void Fighter_EnterSpecialLanding(GOBJ *g,int a,float lag){landing++;g->userdata->state_id=43;}
int Other_Form(int s){return s+1;}
void Hand_Over(GOBJ *g,int s){handovers++;g->userdata->state_id=s;}
int Fighter_IASACheck_JumpF(GOBJ *g){if(g->userdata->input.down&0xC00)g->userdata->state_id=24;return 0;}
int Fighter_IASACheck_JumpAerial(GOBJ *g){if(g->userdata->input.down&0xC00)g->userdata->state_id=27;return 0;}
int Fighter_IASACheck_AllGrounded(GOBJ *g){Fighter_IASACheck_JumpF(g);return 0;}
int Fighter_IASACheck_AllAerial(GOBJ *g){Fighter_IASACheck_JumpAerial(g);return 0;}
int Fighter_IASACheck_AirAttack(GOBJ *g){if(g->userdata->input.down&0x100)g->userdata->state_id=65;return 0;}
int Fighter_IASACheck_AirEscape(GOBJ *g){if(g->userdata->input.down&0x60)g->userdata->state_id=236;return 0;}
static unsigned int native_requested,native_called;
static int PM_TestNative(unsigned int address,GOBJ *g){native_called=address;if(address==native_requested){g->userdata->state_id=99;return 1;}return 0;}
#define PM_NATIVE_CHECK(address,gobj) PM_TestNative(address,gobj)
'''


def test_atomic_ground_choice_launch_delay_hitlag_and_landing(tmp_path):
    ground=dict(t='CTC',w='Larger',a={'t':'FSM','a':'grounded'},b={'f':0})
    branch=dict(t='SACT',ct=ground,e=True,
        a=sequence(setting('FSD','jumpheight',3),dict(t='SACC',c='dojumpheight'),
                   dict(t='SAT',f={'f':3},a=setting('FSM','x_vel',30))),
        ea=setting('FSM','y_vel',-100))
    game=dict(source_programs={'up':dict(tl=[dict(af=0,a=branch)]), 'other':dict(tl=[])})
    source,receipt=motion.build([(373,'up',True),(375,'other',False)],game,5,20)
    assert not receipt['limits']
    compile_and_run(tmp_path,HEADER+source+r'''
int main(void){
    FighterData f={0};GOBJ g={&f};PortMotion *r=&port_motion[0];float y;int count;
    f.state_id=373;f.facing_direction=1;f.attr.gravity=.1f;f.attr.terminal_velocity=3;
    f.attr.aerial_drift_max=2;f.attr.aerial_drift_base=.02f;
    PM_Load(&f);PM_Enter(&g);t_frame[0]=1;PM_Phys(&g);
    assert(f.phys.air_state && f.phys.self_vel.Y>1); // The other branch cannot run after launch.
    assert(f.phys.self_vel.X==0 && f.attr.aerial_drift_base==.02f);
    y=f.phys.self_vel.Y;count=r->count;f.flags.hitlag=1;t_frame[0]=4;PM_Phys(&g);
    assert(f.phys.self_vel.Y==y && r->count==count && f.phys.self_vel.X==0);
    f.flags.hitlag=0;PM_Phys(&g);
    assert(fabsf(f.phys.self_vel.X-2.5f)<.001f); // Parent branch selected while grounded, delay fires in air.
    f.phys.self_vel.Y=-1;land=1;PM_Coll(&g);assert(landing==1 && ledge==1 && !f.phys.air_state);
    f.state_id=373;PM_Enter(&g);t_frame[0]=1;PM_Phys(&g);
    f.state_id=375;PM_Enter(&g);f.phys.self_vel.X=0;t_frame[0]=10;PM_Phys(&g);
    assert(f.phys.self_vel.X==0); // Cancelled move's delayed work cannot fire in a later move.
    PM_Load(&f);assert(r->data[0]==0);
    return 0;
}
''')


def test_unsupported_guard_does_not_promote_its_launch_or_scheduled_children():
    branch=dict(t='SACT',ct={'t':'UnknownInput'},a=sequence(dict(t='SACC',c='dojumpheight'),
        dict(t='SAT',f={'f':2},a=setting('FSM','y_vel',100))))
    source,receipt=motion.build([(373,'up',True)],dict(source_programs={'up':dict(tl=[dict(af=0,a=branch)])}),5,20)
    assert receipt['limits'] and not receipt['carried'] and receipt['scheduled_actions']==0
    assert 'PM_Schedule(r,0,' not in source


def test_computed_unbound_scalar_is_an_explicit_unsupported_expression():
    with pytest.raises(expr.Unsupported,match='unbound scalar'):
        expr.scalar({'t':'FSAN','a':{'f':1}}, {})


def test_normal_generic_route_installs_movement_without_replacing_custom_adapters():
    from fighter_port import own_template
    from test_own_template import a_ctx
    moves = {'game_'+clip:dict(slapcity_move='up') for clip in own_template.CLIPS}
    game=dict(game='slapcity',unit=5,source_programs={'up':dict(tl=[dict(af=0,
        a=sequence(setting('FSD','jumpheight',3),dict(t='SACC',c='dojumpheight')))])})
    ctx=a_ctx(moves=moves,source_game=game,generic_specials=True)
    built,why=own_template.build(ctx)
    assert why is None and all(row['phys']=='PM_Phys' for row in built['rows'])
    source='\n'.join(built['source'])
    assert 'PM_Enter(gobj);' in source and 'PM_Load(fd);' in source
    assert built['numbers']['movement']['carried']
    built,why=own_template.build(dict(ctx,generic_specials=False))
    assert why is None and all(row['phys']=='Plain_Phys' for row in built['rows'])
    assert 'PM_Enter(gobj)' not in '\n'.join(built['source'])


def test_recurring_hooks_sample_live_input_expire_and_clear_on_interruption(tmp_path):
    held=dict(t='CTI',i=dict(t='Special',c='Held'),f=1,b='None')
    branch=dict(t='SACT',ct=held,a=setting('FSM','x_vel',dict(t='FSI',i='ctrlY')),
                e=True,ea=setting('FSM','x_vel',0))
    hook=dict(t='SAAA',p='PreMoveUpd',f=dict(f=4),i='aim',a=branch)
    game=dict(source_programs={'aim':dict(tl=[dict(af=0,a=hook)]),'other':dict(tl=[])})
    source,receipt=motion.build([(373,'aim',False),(375,'other',False)],game,60,20)
    assert not receipt['limits']
    compile_and_run(tmp_path,HEADER+source+r'''
int main(void){
    FighterData f={0};GOBJ g={&f};PortMotion *r=&port_motion[0];
    f.state_id=373;f.facing_direction=1;f.phys.air_state=1;
    f.attr.terminal_velocity=3;PM_Load(&f);PM_Enter(&g);
    t_frame[0]=1;PM_Phys(&g);assert(f.phys.self_vel.X==0);
    f.input.held=512;f.input.down=512;f.input.lstick.Y=.8f;
    t_frame[0]=2;PM_Phys(&g);assert(f.phys.self_vel.X==0); // Down differs from Held.
    f.input.down=0;t_frame[0]=3;PM_Phys(&g);assert(f.phys.self_vel.X==.8f);
    f.input.lstick.Y=.4f;t_frame[0]=4;PM_Phys(&g);assert(f.phys.self_vel.X==.4f);
    f.input.lstick.Y=.9f;t_frame[0]=5;PM_Phys(&g);assert(f.phys.self_vel.X==.4f);
    assert(!r->hooks[0].live); // Finite source duration expires.
    PM_Listen(r,0,12,0,5);PM_Unlisten(r,0,12);assert(!r->hooks[0].live);
    PM_Listen(r,0,12,0,5);f.state_id=375;PM_Enter(&g);assert(!r->hooks[0].live);
    assert(PM_InsideSegment(0,-.8f,16));assert(PM_InsideSegment(-.8f,0,256));
    assert(!PM_InsideSegment(0,.8f,16));
    return 0;
}
''')
