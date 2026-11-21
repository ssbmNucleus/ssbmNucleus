"""Explicit source velocity events on ordinary native actions.

Rivals window velocities belong to the source simulation, not the visual root animation. Custom
special modules own their movement; this shared path handles ordinary actions and reports unknown
modifiers/types rather than guessing how the source game evaluates them.
"""
from __future__ import annotations
import math

KINDS = {'None':0,'SetVelocity':1,'AddVelocity':2,'MultiplyVelocity':3,'ConstVelocity':4}


def collect(played, moves, script_for, drawn=1.0):
    """Return generated events and an explicit coverage receipt, for {action: clip stem}."""
    rows, skipped = [], []
    for action, stem in sorted(played.items()):
        if not stem or action >= 295:
            continue  # custom states already have their own movement callbacks
        script = script_for(stem,moves)
        move = moves.get(script) or {}
        if not move.get('rivals2_attack'):
            continue
        air = 'attackair' in script
        for event in move.get('momentum') or []:
            context = dict(action=action,script=script,window=event.get('window'))
            if not script.startswith('game_attack'):
                skipped.append(dict(context,reason='engine-positioned grab/throw/ledge states need a dedicated movement adapter',event=event))
                continue
            if 'last' not in event or 'modifiers' not in event:
                raise ValueError(f'{script}: velocity intervals/modifiers missing; rerun the Rivals reader')
            kinds = [event.get('x_kind'),event.get('y_kind')]
            if event['modifiers'] or any(k not in KINDS for k in kinds):
                skipped.append(dict(context,reason='source velocity modifier or type needs a custom implementation',event=event))
                continue
            first,last = int(event['real']),int(event['last'])
            if first < 1 or last < first:
                raise ValueError(f'{script}: invalid source velocity interval {first}..{last}')
            if not air and kinds[1] != 'None':
                skipped.append(dict(context,reason='ground vertical velocity needs explicit ground/air transition behavior',event=event))
                continue
            values=[float(event['x']),float(event['y'])]
            if not all(math.isfinite(v) for v in values):
                raise ValueError(f'{script}: non-finite source velocity')
            for axis,kind,value in zip('xy',kinds,values):
                if kind=='None' and value:
                    skipped.append(dict(context,axis=axis,value=value,reason='None velocity is owned by source compiled behavior'))
            if kinds==['None','None']:
                continue
            values=[v if k=='MultiplyVelocity' else v*drawn for v,k in zip(values,kinds)]
            rows.append(dict(context,first=first,last=last,x_kind=KINDS[kinds[0]],y_kind=KINDS[kinds[1]],
                             x=values[0],y=values[1]))
    return rows,dict(events=rows,not_carried=skipped)


RUNTIME = '''
// Installed after this fighter's existing IASA process, before the engine's physics priority.
// HSD_GObjProc_8038FAA8 inserts a new same-priority process after this GObj's existing one.
typedef struct {int action,first,last,x_kind,y_kind; float x,y;} MomentumEvent;
static const MomentumEvent momentum_events[] = {
@rows@
};
static u8 momentum_registered[6];
static int momentum_state[6],momentum_action[6];
static float momentum_frame[6];
static void (*momentum_original[6])(GOBJ *);
static void Momentum_Load(FighterData *fd)
{
    int p = fd->ply;
    momentum_registered[p] = 0;
    momentum_state[p] = -1;
    momentum_action[p] = -1;
    momentum_frame[p] = 0;
    momentum_original[p] = 0;
}
static void Momentum_Change(float *speed, int kind, float amount, float facing)
{
    if (kind == 1)
        *speed = amount * facing;
    else if (kind == 2)
        *speed += amount * facing;
    else if (kind == 3)
        *speed *= amount;
    else if (kind == 4)
        *speed = amount * facing;
}
static void Momentum_Phys(GOBJ *gobj)
{
    FighterData *fd = gobj->userdata;
    int p = fd->ply, state = fd->state_id, action = fd->action_id, i, grounded;
    float now = fd->state.frame, before = momentum_frame[p];
    if (fd->flags.hitlag)
        return;
    grounded = fd->phys.air_state == 0;
    // Set/add/multiply are entry impulses. Constant velocity is enforced after ordinary friction/gravity.
    for (i = 0; i < sizeof(momentum_events) / sizeof(momentum_events[0]); i++)
    {
        const MomentumEvent *e = &momentum_events[i];
        if (e->action != action || !(before < e->first && now >= e->first))
            continue;
        if (e->x_kind && e->x_kind != 4)
            Momentum_Change(grounded ? &fd->phys.self_vel_ground.X : &fd->phys.self_vel.X,
                            e->x_kind, e->x, fd->facing_direction);
        if (!grounded && e->y_kind && e->y_kind != 4)
            Momentum_Change(&fd->phys.self_vel.Y, e->y_kind, e->y, 1.0f);
    }
    if (momentum_original[p])
        momentum_original[p](gobj);
    if (fd->state_id != state || fd->action_id != action)
        return;
    for (i = 0; i < sizeof(momentum_events) / sizeof(momentum_events[0]); i++)
    {
        const MomentumEvent *e = &momentum_events[i];
        if (e->action != action || now < e->first || now >= e->last + 1.0f)
            continue;
        if (e->x_kind == 4)
        {
            Momentum_Change(grounded ? &fd->phys.self_vel_ground.X : &fd->phys.self_vel.X,
                            4, e->x, fd->facing_direction);
            if (grounded)
            {
                // Ground friction is queued at +0xE4, then added to velocity after this callback.
                // A constant owns this axis; retain independent knockback, but remove control acceleration.
                fd->phys.horzitonal_velocity_queue_will_be_added_to_0xec = 0;
                fd->phys.vertical_velocity_queue_will_be_added_to_0xec = 0;
                Fighter_PhysGround_ApplyVelocity(gobj);
            }
        }
        if (!grounded && e->y_kind == 4)
            Momentum_Change(&fd->phys.self_vel.Y, 4, e->y, 1.0f);
    }
    momentum_frame[p] = now;
}
static void Momentum_AfterInput(GOBJ *gobj)
{
    FighterData *fd = gobj->userdata;
    int p = fd->ply, i, carries = 0;
    if (fd->flags.hitlag)
        return;
    if (fd->state_id != momentum_state[p] || fd->action_id != momentum_action[p] ||
        fd->state.frame < momentum_frame[p])
        momentum_frame[p] = 0;
    momentum_state[p] = fd->state_id;
    momentum_action[p] = fd->action_id;
    for (i = 0; i < sizeof(momentum_events) / sizeof(momentum_events[0]); i++)
        if (momentum_events[i].action == fd->action_id)
            carries = 1;
    if (carries)
    {
        if (fd->cb.Phys != Momentum_Phys)
        {
            momentum_original[p] = fd->cb.Phys;
            fd->cb.Phys = Momentum_Phys;
        }
    }
    else
    {
        if (fd->cb.Phys == Momentum_Phys)
            fd->cb.Phys = momentum_original[p];
        momentum_frame[p] = fd->state.frame;
    }
}
static void Momentum_Register(FighterData *fd, GOBJ *gobj)
{
    if (!momentum_registered[fd->ply])
    {
        // Registration happens in the first OnFrame, after the engine installed all fighter processes.
        GObj_AddProc(gobj, Momentum_AfterInput, FTPRI_IASA);
        momentum_registered[fd->ply] = 1;
    }
}

'''


def source(rows):
    """Shared C definitions; install registration from OnFrame and reset from OnLoad."""
    records=[]
    for e in rows:
        records.append('    {'+', '.join(str(int(e[k])) for k in ('action','first','last','x_kind','y_kind'))+
                       f", {float(e['x'])!r}f, {float(e['y'])!r}f"+'},')
    return RUNTIME.replace('@rows@','\n'.join(records)).splitlines()
