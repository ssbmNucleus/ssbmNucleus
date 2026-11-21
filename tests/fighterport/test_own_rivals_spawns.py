from fighter_port import own_rivals_spawns as spawns
from test_rivals_article_programs import fixture
from host_c import compile_and_run


def context():
    data,_=fixture()
    game=dict(fighter='test',projectiles={'shot':data},article_models={'shot':dict(folder='article_shot',bounds=[[-2,-2,-2],[2,2,2]])})
    creation=dict(id='shot',real=3,window='Release',offset=[5,1],source_creation=dict(ArticleInitialWindowStringTableKey='Launch'))
    move=dict(rivals2_attack='Nspecial',articles=[creation])
    return dict(source_game=game,drawn=1),move


def test_native_spawn_uses_owner_facing_floor_clearance_and_never_repeats_during_hitlag(tmp_path):
    ctx,move=context()
    source,items,load,receipt=spawns.build(ctx,[(373,300,move,False),(374,301,move,False)])
    assert len(items)==1 and not receipt['limits']
    compile_and_run(tmp_path,r'''
#include <assert.h>
typedef struct {float X,Y,Z;} Vec;
typedef struct {int ply,state_id;float facing_direction;struct{int hitlag;} flags;struct{int air_state;Vec pos;} phys;} FighterData;
typedef struct {struct{int var1;} item_var;} ItemData;
typedef struct{void *userdata;} GOBJ;
typedef struct {GOBJ *parent_gobj,*parent_gobj2;int it_kind;Vec pos,pos2;float facing_direction;int is_raycast_below;} SpawnItem;
static SpawnItem made;static ItemData item;static GOBJ ig={&item};static int spawned,physics;
static unsigned rp_fired[6];static int t_frame[6];
int MEX_GetFtItemID(GOBJ *g,int which){return which;}
GOBJ *Item_CreateItem1(SpawnItem *s){made=*s;spawned++;return &ig;}
void ItemStateChange(GOBJ *g,int state,int flags){}
void Item_CopyDevelopState(GOBJ *item,GOBJ *owner){}
void RV_Phys(GOBJ *g){physics++;}
'''+source+r'''
int main(void){
    FighterData f={0};GOBJ g={&f};f.state_id=373;f.facing_direction=-1;f.phys.pos.X=20;
    t_frame[0]=2;RP_Phys(&g);assert(!spawned);
    t_frame[0]=3;f.flags.hitlag=1;RP_Phys(&g);assert(!spawned);
    f.flags.hitlag=0;RP_Phys(&g);assert(spawned==1 && made.pos.X==15 && made.pos.Y>2);
    assert(made.parent_gobj==&g && made.facing_direction==-1 && item.item_var.var1==1);
    RP_Phys(&g);f.state_id=374;RP_Phys(&g);assert(spawned==1); // Same cast survives ground/air handover.
    rp_fired[0]=0;f.phys.air_state=1;RP_Phys(&g);assert(spawned==2 && made.pos.Y==1);
    return 0;
}
''')


def test_compiled_trigger_is_never_guessed_and_named_policy_is_explicit():
    ctx,move=context();move['articles'][0]['real']=None
    source,items,load,receipt=spawns.build(ctx,[(373,300,move,False)])
    assert not source and not items and 'compiled article creation' in receipt['limits'][0]
    ctx['source_game']['fighter']='loxodont';move['articles'][0]['id']='moltenboulder'
    move['windows']=[(1,'Charging',10),(11,'Active Ground',6)]
    first,options,notes=spawns.policy(ctx['source_game'],move,move['articles'][0])
    assert first==11 and options['on_hit']=='Destroy' and 'not carried' in notes[-1]


def test_multiple_declared_casts_in_one_window_keep_separate_spawn_permissions():
    import copy
    ctx,move=context();second=copy.deepcopy(move['articles'][0])
    second['real']=5;second['source_creation']['CreationWindowFrame']=2
    move['articles'].append(second)
    source,items,load,receipt=spawns.build(ctx,[(373,300,move,False)])
    assert len(items)==1 and not receipt['limits']
    assert 't_frame[fd->ply]==3' in source and 't_frame[fd->ply]==5' in source
    assert '(1u<<0)' in source and '(1u<<1)' in source
