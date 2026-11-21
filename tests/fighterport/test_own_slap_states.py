"""Execute source transitions, not merely their generated labels."""
from fighter_port import own_slap_motion as motion, own_slap_states as states, own_template
from test_own_slap_motion import HEADER, setting, sequence
from host_c import compile_and_run
from test_own_template import a_ctx, DONOR_ACTIONS


def cancel(name, soft=0):
    return dict(t='SACTM', tm=name, s=soft)


def program(*actions):
    return dict(tl=[dict(af=frame, a=action) for frame, action in actions])


def trigger(action, duration=0):
    return dict(t='SAIA', ti=duration, tr=dict(sf=1,b='None',e='None',
                v=dict(t='Special',c='Down'),a=action))


NATIVE_HEADER = HEADER.replace('struct {float gravity,', 'struct {int max_jumps;float gravity,')
NATIVE_HEADER = NATIVE_HEADER.replace('} FighterData;', 'struct {int jumps_used;} jump;\n} FighterData;')
NATIVE_HEADER += r'''
static void PM_Enter(GOBJ *g);
static void Enter(GOBJ *g,int state){g->userdata->state_id=state;t_frame[0]=1;PM_Enter(g);}
static void Leave(GOBJ *g,int helpless,float landing){g->userdata->state_id=helpless?35:14;}
void Fighter_EnterLanding(GOBJ *g){g->userdata->state_id=42;}
'''


def test_input_followup_consumes_jump_preserves_velocity_and_clears_stale_work(tmp_path):
    follow = trigger(sequence(setting('FSM','jumpsleft',0), setting('FSM','x_vel',12),
                              cancel('up'), setting('FSD','stale',99)))
    initial = sequence(dict(t='SAT',f={'f':8},a=setting('FSD','stale',88)), follow)
    game = dict(source_programs={'start':program((0,initial)),
        'up':program((0,setting('FSM','y_vel',20)), (2,setting('FSD','arrived',1)))})
    source,receipt=motion.build([(373,'start',False),(377,'up',True),(378,'up',True)],game,60,20,
                               destinations={'up':(377,378)})
    assert not receipt['limits'] and receipt['input_triggers']==1
    compile_and_run(tmp_path,NATIVE_HEADER+source+r'''
int main(void){
    FighterData f={0};GOBJ g={&f};PortMotion *r=&port_motion[0];
    f.state_id=373;f.phys.air_state=1;f.facing_direction=-1;f.attr.max_jumps=2;f.jump.jumps_used=1;
    f.attr.terminal_velocity=30;PM_Load(&f);PM_Enter(&g);t_frame[0]=1;PM_Phys(&g);
    assert(f.state_id==373 && f.jump.jumps_used==1);
    f.input.down=512;f.flags.hitlag=1;t_frame[0]=2;PM_Phys(&g);assert(f.state_id==373);
    f.flags.hitlag=0;PM_Phys(&g);
    assert(f.state_id==378 && f.jump.jumps_used==2 && t_frame[0]==1);
    assert(PM_Form(r,378,0)==377 && PM_Form(r,377,1)==378); // Handover keeps the transitioned source program.
    assert(f.phys.self_vel.X==-12 && f.phys.self_vel.Y==20); // Entry executes immediately, once.
    assert(r->data[1]==0 && !r->triggers[0].live); // Old ordered tail and trigger are gone.
    f.input.down=0;t_frame[0]=3;PM_Phys(&g);assert(r->data[2]==1);
    t_frame[0]=20;PM_Phys(&g);assert(r->data[1]==0); // Old delayed action never runs.
    return 0;
}
''')


def test_finite_input_window_priority_common_exit_and_transition_cycle_bound(tmp_path):
    game=dict(source_programs={'start':program((0,sequence(trigger(cancel('loop'),3),
        trigger(cancel('neutral'),2)))), 'loop':program((0,cancel('loop')))})
    source,_=motion.build([(373,'start',False),(375,'loop',False)],game,60,20,
                          destinations={'loop':(375,375),'neutral':(-1,-1)})
    compile_and_run(tmp_path,NATIVE_HEADER+source+r'''
int main(void){
    FighterData f={0};GOBJ g={&f};f.state_id=373;f.facing_direction=1;
    PM_Load(&f);PM_Enter(&g);t_frame[0]=1;PM_Phys(&g);
    f.input.down=512;t_frame[0]=2;PM_Phys(&g);assert(f.state_id==14); // Newest matching trigger wins.
    f.state_id=373;PM_Enter(&g);f.input.down=0;t_frame[0]=1;PM_Phys(&g);
    f.input.down=512;t_frame[0]=4;PM_Phys(&g);assert(f.state_id==373); // Both windows expired.
    Enter(&g,375);PM_Phys(&g);assert(f.state_id==14); // Bad source loop cannot hang native game.
    return 0;
}
''')


def test_unsupported_guard_rolls_back_trigger_registration_and_soft_cancel_is_reported():
    action=dict(t='SACT',ct=dict(t='unknown'),a=trigger(cancel('up')))
    source,receipt=motion.build([(373,'start',False)],dict(source_programs={
        'start':program((0,action),(1,cancel('up',1)))}),60,20,destinations={'up':(377,378)})
    assert receipt['scheduled_actions']==0 and receipt['input_triggers']==0 and not receipt['carried']
    assert any('soft transition' in limit for limit in receipt['limits'])


def test_planner_installs_reachable_followup_and_keeps_source_identity_in_both_forms():
    moves={'game_'+clip:dict(slapcity_move=clip,end=20) for clip in own_template.CLIPS}
    moves['game_specialfinish']=dict(slapcity_move='finish',end=12)
    programs={clip:program() for clip in own_template.CLIPS}
    programs['specialn']=program((5,cancel('finish')))
    # An air follow-up asks for the ground source program explicitly, not specialairn.
    programs['finish']=program((6,cancel('specialn')))
    game=dict(game='slapcity',unit=5,moves=moves,source_programs=programs)
    planned=states.plan(game)
    assert list(planned['clips'])==['specialfinish']
    assert planned['nodes']['specialn',1]['clip']=='specialn'
    ctx=a_ctx(moves=moves,source_game=game,generic_specials=True,
              action={name:295+i for i,name in enumerate(DONOR_ACTIONS)},
              total={name:40 for name in DONOR_ACTIONS})
    built,why=own_template.build(ctx)
    assert why is None and len(built['rows'])==11
    source='\n'.join(built['source'])
    assert all(row['anim']=='PM_Anim' for row in built['rows'])
    assert 'PM_HasDue(gobj,frame)' in source
    assert not built['numbers']['transitions']['limits']
    assert any(note.get('destination')=='finish' for note in built['numbers']['movement']['carried'])


def test_dead_else_missing_and_soft_destinations_do_not_allocate_clips():
    moves={'game_specialn':dict(slapcity_move='start')}
    game=dict(moves=moves,source_programs={'start':program((0,dict(t='SACT',ct={},
        a=cancel('neutral'),e=False,ea=cancel('dead'))),(1,cancel('soft',1)),(2,cancel('missing')))})
    planned=states.plan(game)
    assert not planned['clips'] and len(planned['limits'])==1
    assert 'missing' in planned['limits'][0]


def test_transitions_and_jump_resource_compile_in_the_real_native_module():
    import os, pytest
    from pathlib import Path
    from fighter_port import code, states as native_states
    from test_own_template import donor_rows
    kit=code.toolkit(os.environ.get('MEXTK_DIR') or str(Path.home() / 'projects' / 'm-ex' / 'MexTK'))
    if kit is None:
        pytest.skip('requires MexTK')
    compiler=pytest.importorskip('vault.echo.tier2.build')
    moves={'game_'+clip:dict(slapcity_move=clip,end=40) for clip in own_template.CLIPS}
    moves['game_specialfinish']=dict(slapcity_move='finish',end=12)
    programs={clip:program() for clip in own_template.CLIPS}
    programs['specialn']=program((0,trigger(sequence(setting('FSM','jumpsleft',0),cancel('finish')))))
    programs['finish']=program((8,cancel('neutral')))
    game=dict(game='slapcity',unit=5,moves=moves,source_programs=programs)
    ctx=a_ctx(source_game=game,generic_specials=True,moves=moves,
              action={name:295+i for i,name in enumerate(DONOR_ACTIONS)},
              total={name:40 for name in DONOR_ACTIONS})
    built,why=own_template.build(ctx)
    assert why is None
    rows=donor_rows();built['table']=native_states.table_text(rows,built['rows'])
    files,_=code.source('Marth',own=built,onload=0x801364AC,state_rows=(rows,built['rows']))
    checked=compiler.check_files(files,mextk_dir=str(kit))
    assert checked.get('ok'),checked.get('error')


def test_reading_jump_resource_does_not_overwrite_native_airborne_updates(tmp_path):
    game=dict(source_programs={'launch':program((0,sequence(
        setting('FSD','observed',dict(t='FSM',a='jumpsleft')),
        setting('FSD','jumpheight',3),dict(t='SACC',c='dojumpheight'))))})
    source,_=motion.build([(373,'launch',False)],game,60,20)
    header=NATIVE_HEADER.replace('f->phys.air_state=1;f->phys.self_vel.X=0;',
        'f->phys.air_state=1;f->phys.self_vel.X=0;if(f->jump.jumps_used==0)f->jump.jumps_used=1;')
    compile_and_run(tmp_path,header+source+r'''
int main(void){
FighterData f={0};GOBJ g={&f};f.state_id=373;f.attr.max_jumps=2;f.facing_direction=1;
PM_Load(&f);PM_Enter(&g);t_frame[0]=1;PM_Phys(&g);
assert(f.phys.air_state && f.jump.jumps_used==1);
f.jump.jumps_used=2;t_frame[0]=2;PM_Phys(&g);assert(f.jump.jumps_used==2);
return 0;}
''')
