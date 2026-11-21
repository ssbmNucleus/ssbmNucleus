import math
import pytest
from fighter_port import own_action_slots as slots, own_article_motion as motion
from fighter_port import own_resources as resources, own_batted_item as bat
from fighter_port import own_rivals_states as states, port_mechanics as coverage, port_receipt
from host_c import compile_and_run


def test_explicit_clip_owns_reserved_action_without_erasing_other_donor_phases():
    table={'c03specialn':[dict(target_motion='SpecialNStart'),dict(target_motion='SpecialNEnd')],
           'c03branch':[dict(target_motion='SpecialNEnd')]}
    assert slots.reserve(table,{'branch':'SpecialNEnd'},list(table))=={'SpecialNEnd':'c03branch'}
    assert table['c03specialn']==[dict(target_motion='SpecialNStart')]
    assert table['c03branch']==[dict(target_motion='SpecialNEnd')]
    with pytest.raises(ValueError,match='two explicitly'):
        slots.reserve(table,{'branch':'SpecialNEnd','specialn':'SpecialNEnd'},list(table))
    before={k:list(v) for k,v in table.items()}
    slots.reserve(table,{'absent':'SpecialNStart'},list(table))
    assert table==before


def test_custom_predicates_are_attack_scoped_and_keep_source_prerequisites():
    condition=dict(WindowCancelType='::CharacterSpecific1',WindowCancelPrerequisite='::ShieldDown',NegatePrerequisite=True)
    expr=states.predicate(condition,{('Dspecial','CharacterSpecific1'):'Resource(fd)==1'},'Dspecial')
    assert expr=='(Resource(fd)==1) && (!((fd->input.held & 0x60)))'
    with pytest.raises(ValueError,match='needs a mechanic'):
        states.predicate(condition,{('Dspecial','CharacterSpecific1'):'Resource(fd)==1'},'Nspecial')
    with pytest.raises(ValueError,match='guarded'):
        states.predicate(dict(condition,WindowCancelPrerequisite='::Unknown'),{('Dspecial','CharacterSpecific1'):'Resource(fd)==1'},'Dspecial')


def test_coverage_exposes_new_source_obligations_and_requires_built_handlers():
    game=dict(game='rivals2',fighter='example',moves={'ground':dict(rivals2_attack='Nspecial',
        articles=[dict(id='ball',trigger='compiled')])})
    mine=dict(source=['void Throw(void) {}'],mechanics=[coverage.claim('throw','Throw','Native projectile.',covers=['article:Nspecial:ball'])])
    result=coverage.assess(game,mine)
    assert result['assessed'] and not result['unfinished']
    game['moves']['ground']['articles'].append(dict(id='second',trigger='compiled'))
    result=coverage.assess(game,mine)
    assert result['unfinished']==['article:Nspecial:second']
    notes=port_receipt.package_members(dict(fighter='example',mechanic_coverage=result),'Example')
    assert b'[unfinished]' in notes['PORT_NOTES.txt'] and b'second' in notes['port-implementation.json']
    mine['source']=['void Throw(void);']
    with pytest.raises(ValueError,match='not built'):coverage.assess(game,mine)
    mine['source']=['void Throw(void) {}'];mine['mechanics']*=2
    with pytest.raises(ValueError,match='duplicate'):coverage.assess(game,mine)
    assert not coverage.assess(dict(fighter='unknown'),{})['assessed']


def test_fan_schedule_uses_numbered_source_pulses_and_rejects_ambiguous_data():
    windows=[(10,'Spin Active 1',2),(18,'Spin Active 2',2),(26,'Spin Active Final',2)]
    result=motion.fan_schedule(windows,'Spin Active ',count=3,angle=-35,spread=25)
    assert [x['frame'] for x in result]==[10,18]
    assert result[0]['angle']==pytest.approx(math.radians(-35))
    for bad in ([],[(1,'Spin Active 1',0)],[(1,'Spin Active 1',1),(1,'Spin Active 2',1)]):
        with pytest.raises(ValueError):motion.fan_schedule(bad,'Spin Active ',count=3,angle=0,spread=25)


def test_native_resource_fan_swept_contact_and_damage_batting(tmp_path):
    header=r'''
#include <assert.h>
#include <math.h>
typedef struct {float X,Y,Z;} Vec3;
typedef struct GOBJ {void *userdata,*hsd_object;} GOBJ;
typedef struct {float facing_direction;struct {Vec3 pos;} phys;} FighterData;
typedef struct {Vec3 pos,self_vel;float facing_direction;struct {int var1;} item_var;
unsigned char hurt_num[4];int xdce1;struct {void *jobj;int is_updated,hurt_status;float radius;} it_hurt[2];
struct {int recent,angle;float takedmg_direction;GOBJ *source_fighter;} dmg;} ItemData;
static ItemData ids[16];static GOBJ objects[16];static int made,resets;
static GOBJ *Make_Item(GOBJ *g,int slot,Vec3 *at){int n=made++;assert(n<16);ids[n].pos=*at;objects[n].userdata=&ids[n];return &objects[n];}
static void Item_ResetAllHitPlayers(ItemData *id){resets++;}
static void Item_CreateHurtbox(GOBJ *g,float a,float b,float c,float d,float e,float f,float radius){((ItemData *)g->userdata)->it_hurt[0].radius=radius;}
static void Item_SetHurtboxTangibility(GOBJ *g,int status){ItemData *id=g->userdata;for(int i=0;i<*((unsigned char *)&id->hurt_num);i++)id->it_hurt[i].hurt_status=status;}
'''
    main=r'''
int main(void){
PortResource r;Port_ResourceReset(&r,3);assert(Port_ResourceAdd(&r,5)==3 && r.value==3);
assert(!Port_ResourceSpend(&r,4) && r.value==3);assert(!Port_ResourceSpend(&r,-1));
assert(Port_ResourceSpend(&r,2) && r.value==1);assert(Port_ResourceAdd(&r,-4)==0);
Port_ResourceReset(&r,-1);assert(!r.value && !r.limit);
assert(Port_SegmentCircle(0,0,10,0,5,1,1));assert(!Port_SegmentCircle(0,0,10,0,12,0,1));
assert(Port_SegmentCircle(1,1,1,1,1,1,0));assert(!Port_SegmentCircle(1,1,1,1,2,2,1));
FighterData f={0};GOBJ g={&f};Vec3 at={3,10,0};f.facing_direction=-1;
Port_FireFan(&g,3,at,3,0,0.4f,4.5f,5);
assert(made==3 && ids[1].item_var.var1==1 && ids[1].self_vel.X<0);
assert(fabsf(ids[1].pos.X+ids[1].self_vel.X-(at.X-5))<0.001f);
assert(ids[0].self_vel.Y<0 && ids[2].self_vel.Y>0);
Port_FireFan(&g,3,at,17,0,0,1,0);assert(made==3);
float charge=0;ItemData *id=&ids[1];id->dmg.source_fighter=&g;f.phys.pos.X=id->pos.X+1;
objects[1].hsd_object=&g;id->it_hurt[0].hurt_status=1;Port_EnableBatHurtbox(&objects[1],8);
assert(*((unsigned char *)&id->hurt_num)==1 && id->it_hurt[0].jobj==&g && id->it_hurt[0].hurt_status==0 && id->xdce1);
assert(!Port_BatItem(&objects[1],&charge,4,8) && !resets && charge==0);
id->dmg.recent=8;id->dmg.angle=45;assert(Port_BatItem(&objects[1],&charge,4,8));
assert(charge==0.25f && id->self_vel.X<0 && id->self_vel.Y>0 && resets==1);
id->dmg.recent=30;f.phys.pos.X=id->pos.X-1;Port_BatItem(&objects[1],&charge,4,8);
assert(charge==1 && id->self_vel.X>0 && resets==2);
return 0;}
'''
    compile_and_run(tmp_path,header+resources.SOURCE+motion.SOURCE+bat.SOURCE+main)
