"""Generated source contact guards and cancels execute against native-shaped state."""
from fighter_port import own_slap_motion as motion, own_template
from test_own_slap_motion import HEADER, setting, sequence
from host_c import compile_and_run
from test_own_template import a_ctx


UP_ONLY = dict(dc=['spN','spD','atkN','shield','dodge','grab','atkD','spF','atkF',
                   'strF','airStr','airB','strD','airF','airD','airU','strN','airN','air',
                   'atkdash','strdash'])


def program():
    shield = dict(t='CTC', w='Equal', a=dict(t='FSOH', p='hitwasshield'), b=dict(f=1))
    hit = dict(t='SAOH', h=7, b=-1, a=dict(t='SACT', ct=shield,
               a=setting('FSD', 'connected', 0), e=True, ea=setting('FSD', 'connected', 1)))
    connected = dict(t='CTC', w='Equal', a=dict(t='FSD', i='connected'), b=dict(f=1))
    window = dict(t='SASI', ti=0, cfg=dict(dc=['sp', 'atk', 'str', 'air', 'shield', 'dodge', 'grab']))
    hook = dict(t='SAAA', p='PreMoveUpd', f=dict(f=0), i='cancel', a=dict(t='SACT', ct=connected, a=window))
    return dict(tl=[dict(af=0, a=sequence(setting('FSD', 'connected', 0), hit, hook))])


def test_hit_opens_jump_but_miss_shield_hitlag_and_interruption_do_not(tmp_path):
    source, receipt = motion.build([(373, 'attack', False), (375, 'other', False)],
                                  dict(source_programs={'attack':program(), 'other':dict(tl=[])}), 60, 20)
    assert receipt['contact_hooks'] == 1 and receipt['adaptations']
    compile_and_run(tmp_path, HEADER+source+r'''
int main(void){
    FighterData f={0},victim={0};GOBJ g={&f},target={&victim};PortMotion *r=&port_motion[0];
    f.state_id=373;f.action_id=300;f.facing_direction=1;
    PM_Load(&f);PM_Enter(&g);t_frame[0]=1;PM_Phys(&g);
    f.input.down=0x400;t_frame[0]=2;PM_Phys(&g);
    assert(!PM_InputCancel(&g)); // A whiff does not enable jump.
    PM_OnHit(&g,&target,10,1);t_frame[0]=3;PM_Phys(&g);
    assert(!PM_InputCancel(&g)); // A shield contact does not satisfy the body-hit guard.
    PM_OnHit(&g,&target,10,0);f.flags.hitlag=1;
    PM_Phys(&g);assert(r->pending_count==1 && !PM_InputCancel(&g));
    f.flags.hitlag=0;t_frame[0]=4;PM_Phys(&g);
    assert(PM_InputCancel(&g) && f.state_id==24); // Actual body contact permits native jump.
    f.state_id=375;PM_Enter(&g);t_frame[0]=1;PM_Phys(&g);assert(!PM_InputCancel(&g));
    assert(!r->pending_count && !r->hit_count);
    f.state_id=373;PM_Enter(&g);PM_Phys(&g);
    f.state_id=75;PM_OnHit(&g,&target,10,0);assert(!r->pending_count); // Trade/stale callback cannot revive old move.
    f.state_id=373;PM_Enter(&g);r->input_mask=1;r->input_until=4;
    t_frame[0]=4;assert(!PM_InputCancel(&g)); // Finite window closes.
    return 0;
}
''')


def test_live_scalar_buttons_and_axes_preserve_release_and_facing(tmp_path):
    assignments=sequence(*(setting('FSD', name, dict(t='FSI',i=name))
                           for name in ('special','jump','ctrlX','ctrlMag','atkctrlY','shield')))
    hook=dict(t='SAAA',p='PreMoveUpd',f=dict(f=0),i='sample',a=assignments)
    source, receipt=motion.build([(373,'sample',False)],dict(source_programs={'sample':dict(tl=[dict(af=0,a=hook)])}),60,20)
    assert not receipt['limits']
    compile_and_run(tmp_path, HEADER+source+r'''
int main(void){
    FighterData f={0};GOBJ g={&f};PortMotion *r=&port_motion[0];f.state_id=373;f.facing_direction=-1;
    PM_Load(&f);PM_Enter(&g);t_frame[0]=1;PM_Phys(&g);
    f.input.held=0x600;f.input.lstick.X=.6f;f.input.lstick.Y=.8f;f.input.cstick.Y=-.7f;f.input.trigger=.4f;
    t_frame[0]=2;PM_Phys(&g);
    assert(r->data[1]==1 && r->data[2]==1 && r->data[3]==-.6f);
    assert(fabsf(r->data[4]-1)<.001f && r->data[5]==-.7f && r->data[6]==.4f);
    f.input.held=0;t_frame[0]=3;PM_Phys(&g);assert(r->data[1]==0 && r->data[2]==0);
    return 0;
}
''')


def test_unknown_guard_rolls_back_contact_registration_and_never_runs_body():
    source, receipt=motion.build([(373,'guarded',False)],dict(source_programs={'guarded':dict(tl=[
        dict(af=0,a=dict(t='SACT',ct=dict(t='Unknown'),a=program()['tl'][0]['a']))])}),60,20)
    assert receipt['contact_hooks']==0 and receipt['scheduled_actions']==0 and not receipt['carried']


def test_common_contact_hooks_compile_in_the_real_native_module():
    import os, pytest
    from pathlib import Path
    from fighter_port import code, states
    from test_own_template import donor_rows
    kit=code.toolkit(os.environ.get('MEXTK_DIR') or str(Path.home() / 'projects' / 'm-ex' / 'MexTK'))
    if kit is None: pytest.skip('requires MexTK')
    compiler=pytest.importorskip('vault.echo.tier2.build')
    moves={'game_'+clip:dict(slapcity_move='attack') for clip in own_template.CLIPS}
    game=dict(game='slapcity', unit=5, moves=moves, source_programs={'attack':program()})
    built,why=own_template.build(a_ctx(source_game=game,generic_specials=True,moves=moves))
    assert why is None and 'Contact_Load(fd,gobj);' in built['load']
    assert all(row['iasa'].startswith('PM_') for row in built['rows'])
    rows=donor_rows();built['table']=states.table_text(rows,built['rows'])
    files,_=code.source('Marth',own=built,onload=0x801364AC,state_rows=(rows,built['rows']))
    checked=compiler.check_files(files,mextk_dir=str(kit))
    assert checked.get('ok'),checked.get('error')


def test_directional_permissions_select_only_allowed_native_attacks_and_specials(tmp_path):
    from fighter_port import own_slap_input as inputs
    mask, limits=inputs.standard_mask(UP_ONLY)
    assert mask == inputs.STANDARD['jump'] | inputs.STANDARD['spU'] | inputs.STANDARD['atkU'] | inputs.STANDARD['strU']
    assert not limits
    assert inputs.standard_mask(dict(dc=['sp','atk','str','air','jump','shield','dodge','grab']))[0] == 0
    assert inputs.standard_mask({})[0] == 2
    source,_=motion.build([(373,'attack',False)],dict(source_programs={'attack':dict(tl=[
        dict(af=0,a=dict(t='SASI',ti=5,cfg=UP_ONLY))])}),60,20,
        special_entries=dict(n=373,n_air=374,hi=377,hi_air=378,lw=379,lw_air=380,s=375,s_air=376))
    header=HEADER+'\nstatic void Enter(GOBJ *g,int state){g->userdata->state_id=state;}\n'
    compile_and_run(tmp_path,header+source+r'''
int main(void){
    FighterData f={0};GOBJ g={&f};PortMotion *r=&port_motion[0];f.state_id=373;f.facing_direction=1;
    PM_Load(&f);PM_Enter(&g);t_frame[0]=1;PM_Phys(&g);
    native_requested=0x8008BFC4;assert(!PM_InputCancel(&g)); // Disabled forward smash cannot fire.
    native_requested=0x8008B980;assert(PM_InputCancel(&g) && f.state_id==99); // Enabled up tilt.
    f.state_id=373;native_requested=0x8008C830;assert(PM_InputCancel(&g)); // Enabled up smash.
    f.state_id=373;native_requested=0;f.input.down=0x200;f.input.lstick.X=1;
    assert(!PM_InputCancel(&g)); // Disabled side special cannot fire.
    f.input.lstick.X=0;f.input.lstick.Y=1;
    assert(PM_InputCancel(&g) && f.state_id==377); // Ground source up-special entry.
    f.state_id=373;f.phys.air_state=1;
    assert(PM_InputCancel(&g) && f.state_id==378); // Same permission selects its aerial form.
    f.state_id=373;t_frame[0]=6;assert(!PM_InputCancel(&g)); // Finite window expires.
    return 0;
}
''')
