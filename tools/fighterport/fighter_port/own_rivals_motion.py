"""Source-window physics for custom Rivals specials.

Use the reader's velocity events and the attack's movement properties. Native
grounding, ledges, state transitions, and bespoke compiled mechanics stay with
the special adapter. No source-game harness is required to build this code.
"""
import math
from .own_momentum import KINDS


def number(value):
    value = float(value)
    if not math.isfinite(value):
        raise ValueError('Non-finite Rivals movement value')
    return f'{value!r}f'


def physics(name, bindings, scale=1.0):
    """Generate a physics callback for {action: (reader move, source attack)}.

    Positive vertical impulses launch a grounded fighter. Constants own their
    axes; impulses apply once. -1 movement properties use native attributes.
    Unsupported velocity modifiers must be handled by the calling adapter.
    """
    setup, impulses = [], []
    for action, (move, attack) in sorted(bindings.items()):
        properties = {w['StringTableKey']: w.get('MovementProperties') or {} for w in attack['Windows']}
        setup.append(f'    case {int(action)}:')
        impulses.append(f'    case {int(action)}:')
        for first, window, length in move['windows']:
            prop = properties[window]
            lines = []
            for source, target in [('Gravity','gravity'),('MaxFallSpeed','limit')]:
                v = float(prop.get(source,-1))
                if v >= 0:
                    lines.append(f'{target} = {number(v*0.1*scale)};')
            drift = prop.get('CanDrift','::Default').split('::')[-1]
            if drift == 'NoDrift':
                lines.append('drift = 0;')
            for source, target in [('AirAcceleration','accel'),('AirSpeedHorizontalMax','maxspeed')]:
                v = float(prop.get(source,-1))
                if v >= 0:
                    lines.append(f'{target} = {number(v*0.1*scale)};')
            if lines:
                setup.append(f'        if (frame >= {int(first)} && frame < {int(first+length)}) {{ '+ ' '.join(lines)+' }')
        for event in move.get('momentum') or []:
            if event.get('modifiers'):
                raise ValueError(f'{name}: source velocity modifiers need an explicit adapter')
            for axis in 'yx':
                kind, value = event[axis+'_kind'], float(event[axis])
                if kind not in KINDS:
                    raise ValueError(f'{name}: unsupported velocity type {kind}')
                if kind == 'None':
                    if value:
                        raise ValueError(f'{name}: compiled {axis} velocity needs an explicit adapter')
                    continue
                amount = number(value if kind == 'MultiplyVelocity' else value*scale)
                first, last = int(event['real']), int(event['last'])
                condition = f'frame >= {first} && frame <= {last}' if kind == 'ConstVelocity' else f'frame == {first}'
                op = {'SetVelocity':'=', 'ConstVelocity':'=', 'AddVelocity':'+=', 'MultiplyVelocity':'*='}[kind]
                facing = ' * fd->facing_direction' if axis=='x' and kind!='MultiplyVelocity' else ''
                lines=[]
                if axis=='y':
                    if value > 0 and kind in ('SetVelocity','AddVelocity','ConstVelocity'):
                        lines.append('if (!fd->phys.air_state) Fighter_SetAirborne(fd);')
                    lines.append(f'if (fd->phys.air_state) fd->phys.self_vel.Y {op} {amount};')
                else:
                    lines.append(f'if (fd->phys.air_state) fd->phys.self_vel.X {op} {amount}{facing};')
                    lines.append(f'else {{ fd->phys.self_vel_ground.X {op} {amount}{facing}; ground_owned = 1; }}')
                impulses.append(f'        if ({condition}) {{ '+ ' '.join(lines)+' }')
        setup.append('        break;')
        impulses.append('        break;')
    return '''void @name@(GOBJ *gobj)
{
    FighterData *fd = gobj->userdata;
    int frame = t_frame[fd->ply], drift = 1, ground_owned = 0;
    float gravity = fd->attr.gravity, limit = fd->attr.terminal_velocity;
    float accel = fd->attr.aerial_drift_stick_mult, maxspeed = fd->attr.aerial_drift_max;
    float old_accel = accel, old_base = fd->attr.aerial_drift_base, old_max = maxspeed;
    if (fd->flags.hitlag) return;
    switch (fd->action_id) {
@setup@
    }
    if (fd->phys.air_state)
    {
        Fighter_PhysAir_ApplyGravity(fd, gravity, limit);
        if (drift)
        {
            fd->attr.aerial_drift_stick_mult = accel;
            fd->attr.aerial_drift_base = 0;
            fd->attr.aerial_drift_max = maxspeed;
            Fighter_PhysAir_ApplyAerialDrift(fd);
            fd->attr.aerial_drift_stick_mult = old_accel;
            fd->attr.aerial_drift_base = old_base;
            fd->attr.aerial_drift_max = old_max;
        }
    }
    else Fighter_PhysGround_ApplyFriction(gobj);
    switch (fd->action_id) {
@impulses@
    }
    if (ground_owned && !fd->phys.air_state)
    {
        fd->phys.horzitonal_velocity_queue_will_be_added_to_0xec = 0;
        fd->phys.vertical_velocity_queue_will_be_added_to_0xec = 0;
        Fighter_PhysGround_ApplyVelocity(gobj);
    }
}
'''.replace('@name@',name).replace('@setup@','\n'.join(setup)).replace('@impulses@','\n'.join(impulses))


def generic(bindings, game, scale, landing, branches=False, article_adapter=False):
    """Supported source-window physics for template states, with explicit gaps.

    bindings: (native state, native action, reader move, helpless). A modified
    event is not made unconditional; unrelated supported events remain usable.
    """
    from copy import deepcopy
    from .own_kit import fill
    selected, cases, carried, limits, steer, adaptations = {}, [], [], [], [], []
    for state, action, move, helpless in bindings:
        name=move.get('rivals2_attack')
        attack=(game.get('source_attacks') or {}).get(name)
        if not attack:
            limits.append(f'{name or action}: source attack windows are missing')
            continue
        clean=deepcopy(move);clean['momentum']=[]
        for original in move.get('momentum') or []:
            event=deepcopy(original)
            context=f'{name}/{event.get("window")}'
            if event.get('modifiers'):
                modifiers=event['modifiers']
                recognized=all(m.get('ModifierInput','').endswith('::AnalogForward') and
                               m.get('ModifierVelocityType','').endswith('::ChangeAngle') for m in modifiers)
                recognized=recognized and event['x_kind']==event['y_kind'] and event['x_kind'] in ('SetVelocity','ConstVelocity')
                if not recognized:
                    limits.append(f'{context}: velocity modifiers need an adapter')
                    continue
                for modifier in modifiers:
                    angle=math.radians(float(modifier['AngleChange']))
                    active=(f'frame >= {int(event["real"])} && frame <= {int(event["last"])}'
                            if 'ConstVelocity' in (event['x_kind'],event['y_kind']) else f'frame == {int(event["real"])}')
                    steer.append(f'if(fd->action_id=={action} && ({active})) RV_Tilt(fd,{number(angle)});')
                event['modifiers']=[]
                adaptations.append(f'{context}: source angle range with native forward-stick steering; modifier offset deferred')
            for axis in 'xy':
                kind=event.get(axis+'_kind')
                if kind not in KINDS or (kind=='None' and float(event[axis])!=0):
                    limits.append(f'{context}: compiled {axis} velocity needs an adapter')
                    event[axis+'_kind']='None';event[axis]=0
            if event['x_kind']=='None' and event['y_kind']=='None':continue
            if int(event['real'])<1 or int(event['last'])<int(event['real']):
                raise ValueError(f'{context}: invalid source velocity interval')
            clean['momentum'].append(event)
            carried.append(dict(source=name,window=event.get('window'),first=event['real'],last=event['last']))
        selected[action]=(clean,attack)
        ledge=move.get('ledge_grab')
        cases.append(f'case {state}: ledge={int(ledge) if ledge is not None else 30000}; helpless={int(helpless)}; break;')
        if move.get('articles') and not article_adapter:limits.append(f'{name}: source article classes need an adapter')
        if not branches and (move.get('window_cancels') or move.get('path_end')):
            limits.append(f'{name}: conditional follow-ups/loops need a state adapter')
    source=physics('RV_BasePhys' if steer else 'RV_Phys',selected,scale)
    if steer:
        source+=RV_STEER.replace('@steer@','\n'.join(dict.fromkeys(steer)))
    collision=RV_COLL
    if branches:
        collision=collision.replace('    Fighter_SetGrounded2(fd);', '    Fighter_SetGrounded2(fd);\n    if(RV_Branch(gobj))return;')
        collision=collision.replace('Fighter_SetAirborne(fd);Hand_Over', 'Fighter_SetAirborne(fd);if(RV_Branch(gobj))return;Hand_Over')
    source+=fill(collision,dict(cases='\n'.join(cases),landing=number(landing)))
    return source,dict(carried=carried,limits=list(dict.fromkeys(limits)),
                       adaptations=list(dict.fromkeys(adaptations)),source='Rivals source windows')


RV_STEER=r'''
static void RV_Tilt(FighterData *fd,float angle)
{
    float stick=fd->input.lstick.X*fd->facing_direction,x,y;
    if(stick<0)stick=0;if(stick>1)stick=1;angle*=stick;
    x=fd->phys.self_vel.X*fd->facing_direction;y=fd->phys.self_vel.Y;
    fd->phys.self_vel.X=(x*cos(angle)-y*sin(angle))*fd->facing_direction;
    fd->phys.self_vel.Y=x*sin(angle)+y*cos(angle);
}
void RV_Phys(GOBJ *gobj)
{
    FighterData *fd=gobj->userdata;int frame=t_frame[fd->ply];
    if(fd->flags.hitlag)return;
    RV_BasePhys(gobj);
    @steer@
}
'''


RV_COLL = r'''
static void RV_Landed(GOBJ *gobj)
{
    FighterData *fd=gobj->userdata;int ledge=30000,helpless=0;
    switch(fd->state_id) {@cases@}
    Fighter_SetGrounded2(fd);
    if(helpless)Fighter_EnterSpecialLanding(gobj,0,@landing@);
    else Hand_Over(gobj,Other_Form(fd->state_id));
}
void RV_Coll(GOBJ *gobj)
{
    FighterData *fd=gobj->userdata;int ledge=30000,helpless=0;
    switch(fd->state_id) {@cases@}
    if(!fd->phys.air_state) {
        if(!Fighter_CollGround_PassLedge(gobj)) {
            Fighter_SetAirborne(fd);Hand_Over(gobj,Other_Form(fd->state_id));
        }
    }
    else if(t_frame[fd->ply]>=ledge)
        Fighter_CollAir_GrabFacingLedgeWalljump(gobj,0,RV_Landed);
    else if(Fighter_CollAir_IgnoreLedge_NoCB(gobj))RV_Landed(gobj);
}
'''
