from copy import deepcopy
from echo_rivals2.branches import branch_stem
from fighter_port import own_rivals_states as states, own_template
from test_own_template import a_ctx
from host_c import compile_and_run


def fixture():
    def cancel(kind, target, first, last, **extra):
        return dict(window='Source', first=first, last=last, condition=dict(
            WindowCancelType='::'+kind, PostCancelWindowStringTableKey=target, **extra))
    neutral=dict(rivals2_attack='Nspecial',windows=[(1,'Start',2),(3,'Charge',10),(13,'Release',3)],
        end=16,window_cancels=[cancel('SpecialReleased','Release',3,12)],path_end='')
    up=dict(rivals2_attack='Uspecial',windows=[(1,'Rise',5),(6,'Fall',4)],end=10,
        window_cancels=[cancel('Grounded','Land',6,9)],path_end='Fall')
    land=dict(rivals2_attack='Uspecial',windows=[(1,'Land',3),(4,'Recover',7)],end=11,
        window_cancels=[],path_end='',conditional_only=True)
    moves={'game_specialn':neutral,'game_specialairn':deepcopy(neutral),
           'game_specialhi':up,'game_specialairhi':deepcopy(up)}
    for attack in ('Uspecial','UspecialAir'):
        moves['game_'+branch_stem(attack,'Land')[3:]]=deepcopy(land)
    return dict(game='rivals2',moves=moves)


def test_reachable_paths_reserve_distinct_actions_and_unknown_guards_stay_closed():
    game=fixture()
    plan=states.plan(game)
    assert len(plan['clips'])==2 and len(set(plan['clips'].values()))==2
    assert not set(plan['clips'].values()) & set(own_template.CLIPS.values())
    assert plan['nodes']['specialn']['branches'][0]['target']==('specialn',13)
    assert plan['nodes']['specialhi']['loop']==('specialhi',6)
    assert not plan['limits']
    for clip in ('specialhi','specialairhi'):
        game['moves']['game_'+clip]['window_cancels'][0]['condition']['WindowCancelPrerequisite']='::CharacterSpecific1'
    guarded=states.plan(game)
    assert not guarded['clips']
    assert guarded['nodes']['specialhi']['loop'] is None
    assert any('loop has no supported exit' in message for message in guarded['limits'])
    assert any('guarded Grounded' in message for message in guarded['limits'])


def test_same_source_plan_drives_native_release_loop_landing_and_interrupt_reset(tmp_path):
    game=fixture();plan=states.plan(game)
    actions=dict(a_ctx()['action'])
    actions.update((motion,320+i) for i,motion in enumerate(plan['clips'].values()))
    ctx=a_ctx(source_game=game,moves=game['moves'],generic_specials=True,
              action=actions,total={motion:50 for motion in actions})
    # Exercise apply separately: the generated transition code is independent
    # of source movement and can be driven with real native input/state fields.
    rows=[dict(action=actions[motion]) for motion in own_template.CLIPS.values()]
    source,receipt=states.apply(ctx,'',rows,[],[],20.0)
    assert len(rows)==10 and receipt['carried']
    header=r'''
#include <assert.h>
typedef struct {int ply,state_id;struct{int hitlag;}flags;struct{int air_state;}phys;
struct{int held,down;}input;} FighterData;
typedef struct {void *userdata;} GOBJ;
static int t_frame[6],seek,advances,ground_inputs,air_inputs,left,landed;
static void ActionStateChange(float frame,int rate,int blend,GOBJ *g,int state,int flags,int extra)
{FighterData *fd=g->userdata;fd->state_id=state;seek=(int)frame;}
static void Fighter_AdvanceScript(GOBJ *g){advances++;}
static int Tick(GOBJ *g){FighterData *fd=g->userdata;return ++t_frame[fd->ply];}
static void Leave(GOBJ *g,int helpless,float landing){FighterData *fd=g->userdata;fd->state_id=14;left++;}
static void Fighter_EnterSpecialLanding(GOBJ *g,int unused,float landing){landed++;}
static void Fighter_IASACheck_AllGrounded(GOBJ *g){ground_inputs++;}
static void Fighter_IASACheck_AllAerial(GOBJ *g){air_inputs++;}
'''
    compile_and_run(tmp_path,header+source+r'''
int main(void){
    FighterData f={0};GOBJ g={&f};f.state_id=373;t_frame[0]=3;f.input.held=0x200;
    RV_IASA(&g);assert(t_frame[0]==3 && advances==0);
    f.input.held=0;RV_IASA(&g);assert(t_frame[0]==13 && seek==12 && advances==1);
    RV_Anim(&g);assert(t_frame[0]==14 && f.state_id==373);
    RV_Anim(&g);RV_Anim(&g);assert(left==1 && f.state_id==14);
    f.state_id=377;f.phys.air_state=1;t_frame[0]=9;
    RV_Anim(&g);assert(t_frame[0]==6 && f.state_id==377 && seek==5);
    f.flags.hitlag=1;f.phys.air_state=0;assert(!RV_Branch(&g));
    f.flags.hitlag=0;assert(RV_Branch(&g));assert(f.state_id==381 && t_frame[0]==1);
    t_frame[0]=10;RV_Anim(&g);assert(left==2 && f.state_id==14);
    // There is no stored branch queue: damage/another native state interrupts it.
    f.state_id=75;t_frame[0]=7;assert(!RV_Branch(&g));
    return 0;
}
''')


def test_native_special_land_destination_does_not_require_an_exported_branch():
    game=fixture()
    game['moves']['game_specialhi']['window_cancels'][0]['condition']['PostCancelWindowStringTableKey']='Special Land'
    plan=states.plan(game)
    assert plan['nodes']['specialhi']['branches'][0]['target']==('land',0)


def test_missing_allocated_clip_is_a_build_error_not_a_dead_transition():
    import pytest
    game=fixture();ctx=a_ctx(source_game=game,moves=game['moves'])
    rows=[dict(action=ctx['action'][motion]) for motion in own_template.CLIPS.values()]
    with pytest.raises(ValueError,match='was not installed'):
        states.apply(ctx,'',rows,[],[],20.0)


def test_shared_state_table_and_collision_compile_with_the_native_kit():
    import os, pytest
    from pathlib import Path
    from fighter_port import code, states as table
    from test_own_template import donor_rows
    kit=code.toolkit(os.environ.get('MEXTK_DIR') or str(Path.home() / 'projects' / 'm-ex' / 'MexTK'))
    if kit is None:
        pytest.skip('requires MexTK')
    compiler=pytest.importorskip('vault.echo.tier2.build')
    game=fixture();planned=states.plan(game)
    game['moves']['game_specialhi']['momentum']=[dict(real=1,last=5,window='Rise',x=0,y=7.5,
        x_kind='SetVelocity',y_kind='SetVelocity',modifiers=[dict(ModifierInput='::AnalogForward',
            ModifierVelocityType='::ChangeAngle',AngleChange=-20)])]
    actions=dict(a_ctx()['action'])
    actions.update((motion,320+i) for i,motion in enumerate(planned['clips'].values()))
    game['source_attacks']={}
    for move in game['moves'].values():
        attack=game['source_attacks'].setdefault(move['rivals2_attack'],dict(Windows=[]))
        known={w['StringTableKey'] for w in attack['Windows']}
        attack['Windows'].extend(dict(StringTableKey=name,MovementProperties={})
            for first,name,length in move['windows'] if name not in known)
    ctx=a_ctx(source_game=game,moves=game['moves'],generic_specials=True,
              action=actions,total={motion:50 for motion in actions})
    built,why=own_template.build(ctx)
    assert why is None
    rows=donor_rows();built['table']=table.table_text(rows,built['rows'])
    files,_=code.source('Marth',own=built,onload=0x801364AC,state_rows=(rows,built['rows']))
    checked=compiler.check_files(files,mextk_dir=str(kit))
    assert checked.get('ok'),checked.get('error')
