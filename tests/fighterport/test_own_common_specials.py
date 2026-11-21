from copy import deepcopy
from fighter_port import own_template, own_rivals_motion, port_receipt
from test_own_template import a_ctx
from test_own_rivals_motion import example
from test_own_slap_motion import HEADER
from host_c import compile_and_run
from test_own_slap_projectiles import fixture


def test_template_builds_source_items_with_movement_and_reports_the_remaining_gaps():
    builder=fixture();game=builder.game
    game.update(game='slapcity',source_programs={'spn':dict(tl=[dict(af=1,a=dict(t='SASA',id='shot',b='projectiles'))])})
    moves={'game_'+clip:game['moves']['game_specialn'] for clip in own_template.CLIPS}
    game['moves']=moves
    ctx=a_ctx(source_game=game,generic_specials=True,moves=moves,joints={'hand':9},drawn=.5)
    built,why=own_template.build(ctx)
    assert why is None and len(built['items'])==1
    assert any('MEX_IndexFighterItem' in line for line in built['load'])
    receipt=port_receipt.summarize(dict(route='own skeleton',own_states=built['rows'],code=built['provides'],
        special_numbers=built['numbers'],specials_not_written='custom transitions remain'))
    assert receipt['runtime']=='shared source-program execution with known gaps'
    assert not receipt['placeholder_specials']
    assert 'custom transitions remain' in receipt['limitations']
    assert receipt['adaptations']


def test_rivals_template_uses_shared_physics_and_preserves_unknown_modifier_limits():
    move,attack=example();move['rivals2_attack']='Uspecial'
    move['momentum'][0]['modifiers']=[dict(ModifierVelocityType='::Unknown')]
    moves={'game_'+clip:move for clip in own_template.CLIPS}
    game=dict(game='rivals2',source_attacks={'Uspecial':attack})
    built,why=own_template.build(a_ctx(source_game=game,generic_specials=True,moves=moves))
    assert why is None and all(r['phys']=='RV_Phys' for r in built['rows'])
    movement=built['numbers']['movement']
    assert movement['carried'] and any('modifiers' in gap for gap in movement['limits'])
    custom,why=own_template.build(a_ctx(source_game=game,generic_specials=False,moves=moves))
    assert why is None and all(r['phys']=='Plain_Phys' for r in custom['rows'])


def test_rivals_generic_launch_and_native_landing_with_a_real_callback(tmp_path):
    move,attack=example();move.update(rivals2_attack='Uspecial',ledge_grab=4)
    source,receipt=own_rivals_motion.generic([(373,300,move,True)],dict(source_attacks={'Uspecial':attack}),1,20)
    header=HEADER.replace('self_vel,self_vel_ground;','self_vel,self_vel_ground;float horzitonal_velocity_queue_will_be_added_to_0xec,vertical_velocity_queue_will_be_added_to_0xec;')
    header+='\nvoid Fighter_PhysGround_ApplyVelocity(GOBJ *g){}\n'
    compile_and_run(tmp_path,header+source+r'''
int main(void){
    FighterData f={0};GOBJ g={&f};f.state_id=373;f.action_id=300;f.facing_direction=-1;
    f.attr.gravity=.1f;f.attr.terminal_velocity=3;t_frame[0]=3;RV_Phys(&g);
    assert(f.phys.air_state && f.phys.self_vel.Y==4 && f.phys.self_vel.X==-1);
    t_frame[0]=4;land=1;RV_Coll(&g);
    assert(landing==1 && ledge==1 && f.state_id==43 && !f.phys.air_state);
    return 0;
}
''')


def test_rivals_shared_angle_modifier_keeps_launch_and_steers_toward_facing(tmp_path):
    move,attack=example();move.update(rivals2_attack='Uspecial',ledge_grab=4)
    move['momentum'][1]['modifiers']=[dict(ModifierInput='::AnalogForward',ModifierVelocityType='::ChangeAngle',AngleChange=-20)]
    source,receipt=own_rivals_motion.generic([(373,300,move,True)],dict(source_attacks={'Uspecial':attack}),1,20)
    assert receipt['adaptations'] and not receipt['limits']
    header=HEADER.replace('self_vel,self_vel_ground;','self_vel,self_vel_ground;float horzitonal_velocity_queue_will_be_added_to_0xec,vertical_velocity_queue_will_be_added_to_0xec;')
    header+='\nvoid Fighter_PhysGround_ApplyVelocity(GOBJ *g){}\n'
    compile_and_run(tmp_path,header+source+r'''
int main(void){
    FighterData f={0};GOBJ g={&f};f.state_id=373;f.action_id=300;f.facing_direction=-1;
    f.attr.terminal_velocity=3;f.input.lstick.X=-1;t_frame[0]=3;RV_Phys(&g);
    assert(f.phys.air_state && f.phys.self_vel.Y>3 && f.phys.self_vel.X<-2);
    return 0;
}
''')
