"""Execute common Slap movement programs in generic native special states.

Branches remain atomic and delayed actions are scheduled when their parent runs.
Unknown callbacks/hooks remain explicit gaps; they are never executed as unconditional
movement. The values stay in source units until the native physics boundary.
"""
from __future__ import annotations
import math
from . import own_slap_expr as expr, own_slap_input as inputs


FIELDS = {'gravity':'gravity', 'fallspeed':'fall', 'allowMovement':'drift',
          'airacc':'accel', 'airspeed':'speed', 'x_vel':'x', 'y_vel':'y',
          'grounded':'ground', 'forwarddir':'facing'}
IGNORED = {'SA', 'SAPA', 'SAPSFX', 'SASHC', 'SACH', 'SARA', 'SAEA', 'SASATP', 'SASFX'}


def number(value):
    value = float(value)
    if not math.isfinite(value):
        raise ValueError('Non-finite source movement value')
    return repr(value) + 'f'


class Compiler:
    def __init__(self, articles=None, destinations=None):
        self.articles = articles
        self.destinations = destinations or {}
        self.triggers = 0
        self.jump_resource = False
        self.adaptations = []
        self.hooks = 0
        self.contacts = 0
        self.tags = {}
        self.in_hook = False
        self.in_contact = False
        self.locals = {'jumpheight': 0}
        self.jobs = []
        self.limits = []
        self.carried = []

    def bindings(self, node):
        if isinstance(node, dict):
            if node.get('t') == 'FSM' and node.get('a') in ('jumps', 'jumpsleft'):
                self.jump_resource = True
            if node.get('t') == 'FSD':
                self.locals.setdefault(node['i'], len(self.locals))
            for value in node.values():
                self.bindings(value)
        elif isinstance(node, list):
            for value in node:
                self.bindings(value)
        return {**{('FSM', key): 'r->' + field for key, field in FIELDS.items()},
                ('FSM', 'x_vel_raw'): '(r->x * r->facing)',
                ('FSM', 'jumps'): 'r->jumps',
                ('FSM', 'jumpsleft'): '(fd->attr.max_jumps-r->jumps)',
                ('FSCH', 'grabedge'): 'r->ledge',
                **inputs.bindings(),
                **({('FSOH', 'hitwasshield'): 'r->hit_shield',
                    ('FSOH', 'hitwasinvincible'): '0.0f',
                    ('FSOH', 'hitwasprojectile'): '0.0f'} if self.in_contact else {}),
                **{('FSD', key): f'r->data[{slot}]' for key, slot in self.locals.items()}}

    def scalar(self, node):
        return expr.scalar(node, self.bindings(node)).replace('Slap', 'PM')

    def guard(self, node):
        return expr.condition(node, self.bindings(node), input_condition=inputs.condition).replace('Slap', 'PM')

    def gap(self, context, reason):
        entry = f'{context}: {reason}'
        if entry not in self.limits:
            self.limits.append(entry)

    def job(self, node, context):
        code = self.action(node, context)
        if not code:
            return None
        index = len(self.jobs)
        self.jobs.append(code)
        return index

    def delayed(self, node, delay, context):
        job = self.job(node, context)
        if job is None:
            return ''
        return f'PM_Schedule(r, {job}, now + {number(delay)});'

    def action(self, node, context):
        if not isinstance(node, dict):
            return ''
        kind = node.get('t')
        if kind == 'SAOS':
            return '\n'.join(filter(None, (self.action(child, context) for child in node.get('ac') or [])))
        if kind == 'SACT':
            checkpoint = (len(self.jobs), len(self.carried), self.hooks, self.contacts,
                          len(self.articles.items) if self.articles else 0, self.triggers, len(self.adaptations))
            yes = self.action(node.get('a'), context)
            no = self.action(node.get('ea'), context) if node.get('e') else ''
            if not yes and not no:
                return ''
            try:
                guard = self.guard(node.get('ct'))
            except expr.Unsupported as exc:
                del self.jobs[checkpoint[0]:]
                del self.carried[checkpoint[1]:]
                self.hooks = checkpoint[2]
                self.contacts = checkpoint[3]
                self.triggers = checkpoint[5]
                del self.adaptations[checkpoint[6]:]
                if self.articles:
                    del self.articles.items[checkpoint[4]:]
                    del self.articles.receipt[checkpoint[4]:]
                    self.articles.ids = {k:v for k,v in self.articles.ids.items() if v<checkpoint[4]}
                self.gap(context, f'conditional movement not carried ({exc})')
                return ''
            return f'if ({guard}) {{\n{yes}\n}}' + (f' else {{\n{no}\n}}' if no else '')
        if kind == 'SACTM':
            target = node.get('tm')
            if node.get('s'):
                self.gap(context, f'soft transition to {target} needs preserved animation/configuration')
                return ''
            states = self.destinations.get(target)
            if states is None:
                self.gap(context, f'move transition to {target} has no built destination')
                return ''
            self.carried.append(dict(source=context, call='move transition', destination=target))
            return f'r->next = r->ground>.5f ? {states[0]} : {states[1]}; return;'
        if kind == 'SAIA':
            trigger = node.get('tr') or {}
            duration = node.get('ti', 0)
            if (not isinstance(duration, (int, float)) or not math.isfinite(duration)
                    or trigger.get('b', 'None') != 'None' or trigger.get('e', 'None') != 'None'):
                self.gap(context, 'input trigger duration/event history needs an adapter')
                return ''
            try:
                guard = inputs.validator(trigger.get('v') or {})
            except expr.Unsupported as exc:
                self.gap(context, str(exc))
                return ''
            action = self.action(trigger.get('a'), context)
            if not action:
                return ''
            job = len(self.jobs)
            self.jobs.append(f'if ({guard}) {{\n{action}\n}}')
            slot = self.triggers
            self.triggers += 1
            self.carried.append(dict(source=context, call='input-trigger action'))
            if trigger.get('sf', 1) != 1:
                self.adaptations.append('Input-trigger assist/history uses current native input; buffered presses before the window are not replayed.')
            self.adaptations.append('Repeated registration of the same source input-trigger site refreshes one bounded native callback.')
            return f'PM_Arm(r,{slot},{job},{number(duration)},now);'
        if kind == 'SAT':
            if self.in_hook or node.get('r'):
                self.gap(context, 'repeating/nested movement timer needs an adapter')
                return ''
            delay = node.get('f') or {}
            if set(delay) != {'f'} or not math.isfinite(float(delay['f'])) or delay['f'] < 0:
                self.gap(context, 'dynamic movement timer needs an adapter')
                return ''
            return self.delayed(node.get('a'), delay['f'], context)
        if kind == 'SAAA':
            duration=node.get('f') or {}
            if self.in_hook or node.get('p')!='PreMoveUpd' or set(duration)!={'f'} or not math.isfinite(float(duration['f'])):
                self.gap(context, 'unsupported active-action phase/duration/nesting')
                return ''
            self.in_hook=True
            try:job=self.job(node.get('a'),context)
            finally:self.in_hook=False
            if job is None:return ''
            self.hooks+=1
            tag=self.tags.setdefault(node.get('i',''),len(self.tags))
            self.carried.append(dict(source=context,call='active action',duration=duration['f']))
            return f'PM_Listen(r,{job},{tag},{number(duration["f"])},now);'
        if kind == 'SADA':
            tag=self.tags.setdefault(node.get('d',''),len(self.tags))
            return f'PM_Unlisten(r,{int(node.get("i",0))},{tag});'
        if kind == 'SAOH':
            if self.in_hook or node.get('h', 7) <= 0 or node.get('b', -1) >= 0:
                self.gap(context, 'nested, hurtbox or selected-hitbox contact callback needs an adapter')
                return ''
            self.in_hook = self.in_contact = True
            try: job = self.job(node.get('a'), context)
            finally: self.in_hook = self.in_contact = False
            if job is None: return ''
            self.contacts += 1
            self.carried.append(dict(source=context, call='native body/shield contact callback'))
            return f'PM_BindHit(r,{job});'
        if kind == 'SASI':
            duration = node.get('ti', 0)
            if not isinstance(duration, (int, float)) or not math.isfinite(duration):
                self.gap(context, 'dynamic standard-input duration needs an adapter')
                return ''
            mask, limits = inputs.standard_mask(node.get('cfg'))
            for limit in limits:self.gap(context, limit)
            self.carried.append(dict(source=context, call='standard input', mask=mask))
            return f'r->input_mask={mask}; r->input_until=' + (f'now+{number(duration)};' if duration > 0 else '0;')
        if kind == 'SATTW':
            statements = []
            for key, at in [('aa','ta'), ('ab','tb'), ('ae','af')]:
                if node.get(key):
                    statements.append(self.action(dict(t='SAT', f=node.get(at), a=node[key]), context))
            return '\n'.join(filter(None, statements))
        if kind == 'SASF':
            statements = []
            for assignment in node.get('s') or []:
                target = expr.key(assignment.get('g') or {})
                if target[0] == 'FSI':
                    continue  # FSInput.SetValue is intentionally empty in the source.
                bindings = self.bindings(assignment)
                if isinstance(target[1],(dict,list)) or target not in bindings:
                    if target[0] == 'FSM':
                        self.gap(context, f'{target[1]} uses native collision/movement defaults')
                    continue
                operation = {'Set':'=', 'Add':'+=', 'Sub':'-=', 'Mult':'*=', 'Div':'/='}.get(assignment.get('w'))
                if operation is None:
                    self.gap(context, f'unsupported movement assignment {assignment.get("w")}')
                    continue
                try:
                    rhs = self.scalar(assignment['s'])
                except expr.Unsupported as exc:
                    self.gap(context, str(exc))
                    continue
                if target == ('FSM','jumpsleft'):
                    statements.append(f'{{ float value=fd->attr.max_jumps-r->jumps; value {operation} {rhs}; r->jumps=PMMax(0,PMMin(fd->attr.max_jumps,fd->attr.max_jumps-(int)value)); }}')
                elif target == ('FSM','x_vel_raw'):
                    statements.append(f'{{ float value = r->x * r->facing; value {operation} {rhs}; r->x = value * r->facing; }}')
                else:
                    statements.append(f'{bindings[target]} {operation} {rhs};')
                if target in (('FSM','jumps'), ('FSM','jumpsleft')):
                    statements.append('r->jump_dirty=1;')
                self.carried.append(dict(source=context, target=list(target), operation=assignment['w']))
            return '\n'.join(statements)
        if kind == 'SASA' and self.articles is not None:
            try:
                return self.articles.spawn(node, context, self)
            except expr.Unsupported as exc:
                self.gap(context, str(exc))
                return ''
        if kind == 'SACC' and node.get('c') == 'dojumpheight':
            self.carried.append(dict(source=context, call='dojumpheight'))
            return 'r->ground = 0; r->y = sqrtf(PMMax(0, 2 * r->gravity * r->data[0]));'
        if kind not in IGNORED:
            label = node.get('c') or node.get('m') or node.get('tm') or kind
            self.gap(context, f'{kind} {label} remains outside common movement execution')
        return ''


RUNTIME = r'''
#define PM_LENGTH @length@
#define PM_SPEED (PM_LENGTH / 60.0f)
#define PM_ACCEL (PM_LENGTH / 3600.0f)
#define PM_JOBS @capacity@
#define PM_HOOKS @hooks@
#define PM_CONTACT_HOOKS @contacts@
#define PM_TRIGGERS @triggers@
typedef struct {int job, live; float at;} PMEvent;
typedef struct {int job,live,tag;float born,until;} PMHook;
typedef struct {int job,shield;} PMHit;
typedef struct {int job,live,order;float until;} PMTrigger;
typedef struct {
    float gravity,fall,drift,accel,speed,x,y,ground,facing,ledge,data[@locals@];
    int count,helpless; float landing;
    int state,hit_count,pending_count,input_mask,next,trigger_order,jump_dirty;
    float jumps;
    float hit_shield,input_until;
    int hit_jobs[PM_CONTACT_HOOKS];
    PMHit pending[PM_CONTACT_HOOKS*12];
    PMEvent events[PM_JOBS];
    PMHook hooks[PM_HOOKS];
    PMTrigger triggers[PM_TRIGGERS];
} PortMotion;
static PortMotion port_motion[6];
static int PM_Form(PortMotion *r,int state,int air)
{
    // A hard transition can enter a source program whose usual input uses a
    // different aerial program. Preserve this program when landing/leaving ledges.
    switch(r->state) { @forms@ }
    return Other_Form(state);
}
static void PM_Arm(PortMotion *r,int slot,int job,float duration,float now)
{
    PMTrigger *t=&r->triggers[slot];
    t->job=job;t->live=1;t->order=++r->trigger_order;
    t->until=duration>0 ? now+duration : 0;
}
static void PM_BindHit(PortMotion *r,int job)
{
    if(r->hit_count<PM_CONTACT_HOOKS)r->hit_jobs[r->hit_count++]=job;
}
static void PM_OnHit(GOBJ *owner,GOBJ *other,float damage,int shield)
{
    FighterData *fd=owner->userdata;PortMotion *r=&port_motion[fd->ply];int i;
    if(fd->state_id!=r->state && fd->state_id!=PM_Form(r,r->state,fd->phys.air_state))return;
    for(i=0;i<r->hit_count && r->pending_count<PM_CONTACT_HOOKS*12;i++) {
        r->pending[r->pending_count].job=r->hit_jobs[i];
        r->pending[r->pending_count++].shield=shield;
    }
}
static void PM_NoHurt(GOBJ *owner,GOBJ *other,float damage,int shield){}
#ifndef PM_NATIVE_CHECK
// Melee GALE01 common IASA routines, from its symbol map and ftCo_Wait_IASA.
#define PM_NATIVE_CHECK(address,gobj) (((int (*)(GOBJ *))(address))(gobj))
#endif
static int PM_InputSpecial(GOBJ *gobj,int mask)
{
    FighterData *fd=gobj->userdata;int direction=0,state;
    const int states[8]={@specials@};
    if(!(fd->input.down&0x200))return 0;
    if(fd->input.lstick.Y>=.5f)direction=1;
    else if(fd->input.lstick.Y<=-.5f)direction=2;
    else if(PMAbs(fd->input.lstick.X)>=.5f)direction=3;
    if(!(mask&(4<<direction)))return 0;
    state=states[direction*2+(fd->phys.air_state ? 1 : 0)];
    if(!state)return 0;
    @enter_special@
    return 1;
}
static int PM_InputCancel(GOBJ *gobj)
{
    FighterData *fd=gobj->userdata;PortMotion *r=&port_motion[fd->ply];int state=fd->state_id;
    if(fd->flags.hitlag || (r->helpless && fd->phys.air_state))return 0;
    if(r->input_until>0 && t_frame[fd->ply]>=r->input_until)r->input_mask=0;
    if(r->input_mask&2) {
        if(fd->phys.air_state)Fighter_IASACheck_AllAerial(gobj);
        else Fighter_IASACheck_AllGrounded(gobj);
    }
    else {
        int mask=r->input_mask;
        if(PM_InputSpecial(gobj,mask))return 1;
        if(!fd->phys.air_state) {
            if((mask&32768)&&PM_NATIVE_CHECK(0x800D8990,gobj))return 1; // grab
            if((mask&4096)&&PM_NATIVE_CHECK(0x8008BFC4,gobj))return 1; // forward smash
            if((mask&1024)&&PM_NATIVE_CHECK(0x8008C830,gobj))return 1; // up smash
            if((mask&2048)&&PM_NATIVE_CHECK(0x8008CB44,gobj))return 1; // down smash
            if((mask&512)&&PM_NATIVE_CHECK(0x8008B658,gobj))return 1; // forward tilt
            if((mask&128)&&PM_NATIVE_CHECK(0x8008B980,gobj))return 1; // up tilt
            if((mask&256)&&PM_NATIVE_CHECK(0x8008BB44,gobj))return 1; // down tilt
            if((mask&64)&&PM_NATIVE_CHECK(0x8008A9F8,gobj))return 1; // jab
            if((mask&16384)&&PM_NATIVE_CHECK(0x80099794,gobj))return 1; // spot/roll dodge
            if((mask&8192)&&PM_NATIVE_CHECK(0x80091A4C,gobj))return 1; // shield
            if(mask&1)Fighter_IASACheck_JumpF(gobj);
        }
        else {
            if(mask&65536)Fighter_IASACheck_AirAttack(gobj);
            if(fd->state_id!=state)return 1;
            if(mask&1)Fighter_IASACheck_JumpAerial(gobj);
            if(fd->state_id!=state)return 1;
            if(mask&16384)Fighter_IASACheck_AirEscape(gobj);
        }
    }
    return fd->state_id!=state;
}
static void PM_Listen(PortMotion *r,int job,int tag,float duration,float now)
{
    int i;for(i=0;i<PM_HOOKS;i++)if(!r->hooks[i].live) {
        r->hooks[i].job=job;r->hooks[i].tag=tag;r->hooks[i].born=now;
        r->hooks[i].until=duration<=0 ? 0 : now+duration;r->hooks[i].live=1;return;
    }
}
static void PM_Unlisten(PortMotion *r,int index,int tag)
{
    int i;if(index<0)return;
    for(i=0;i<PM_HOOKS;i++)if(r->hooks[i].live&&r->hooks[i].tag==tag)
        if(index--==0){r->hooks[i].live=0;return;}
}
static void PM_Schedule(PortMotion *r,int job,float at)
{
    if(r->count < PM_JOBS) {
        r->events[r->count].job=job; r->events[r->count].at=at;
        r->events[r->count].live=1; r->count++;
    }
}
static void PM_Run(GOBJ *gobj,int job,float now)
{
    FighterData *fd=gobj->userdata;
    PortMotion *r=&port_motion[fd->ply];
    switch(job) {
@jobs@
    }
}
static void PM_Load(FighterData *fd)
{
    PortMotion *r=&port_motion[fd->ply]; int i;
    r->count=0;r->next=0;r->trigger_order=0;
    for(i=0;i<PM_TRIGGERS;i++)r->triggers[i].live=0;
    r->state=-1;r->hit_count=r->pending_count=r->input_mask=0;
    for(i=0;i<PM_HOOKS;i++)r->hooks[i].live=0;
    for(i=0;i<@locals@;i++)r->data[i]=0;
}
static void PM_Enter(GOBJ *gobj)
{
    FighterData *fd=gobj->userdata;
    PortMotion *r=&port_motion[fd->ply];int i;
    r->count=0;r->next=0;r->trigger_order=0;
    for(i=0;i<PM_TRIGGERS;i++)r->triggers[i].live=0;
    r->helpless=0; r->landing=@landing@;
    r->state=fd->state_id;r->hit_count=r->pending_count=r->input_mask=0;r->input_until=0;
    for(i=0;i<PM_HOOKS;i++)r->hooks[i].live=0;
    r->gravity=fd->attr.gravity/PM_ACCEL;
    r->fall=fd->attr.terminal_velocity/PM_SPEED;
    r->accel=fd->attr.aerial_drift_stick_mult/PM_ACCEL;
    r->speed=fd->attr.aerial_drift_max/PM_SPEED;
    r->drift=1; r->ledge=1;
    switch(fd->state_id) {
@entries@
    }
}
static void PM_Write(GOBJ *gobj,PortMotion *r)
{
    FighterData *fd=gobj->userdata;
    if(r->ground<0.5f && !fd->phys.air_state)Fighter_SetAirborne(fd);
    if((r->facing<0 ? -1 : 1)!=fd->facing_direction) {
        fd->facing_direction=r->facing<0 ? -1 : 1;
        Fighter_SetBoneRotY(fd,0,1.5707963f*fd->facing_direction);
    }
    @write_jumps@
    if(fd->phys.air_state) {
        fd->phys.self_vel.X=r->x*PM_SPEED*fd->facing_direction;
        fd->phys.self_vel.Y=r->y*PM_SPEED;
    }
    else fd->phys.self_vel_ground.X=r->x*PM_SPEED*fd->facing_direction;
}
static int PM_HasDue(GOBJ *gobj,int frame)
{
    FighterData *fd=gobj->userdata;PortMotion *r=&port_motion[fd->ply];int i;
    for(i=0;i<r->count;i++)if(r->events[i].live && r->events[i].at<=frame)return 1;
    return 0;
}
static int PM_Transfer(GOBJ *gobj,PortMotion *r,int budget)
{
    int state=r->next;
    PM_Write(gobj,r);
    @transfer@
    return 0;
}
void PM_Phys(GOBJ *gobj)
{
    FighterData *fd=gobj->userdata;
    PortMotion *r=&port_motion[fd->ply];
    int i, next, order, previous, transitions=8, budget=PM_JOBS; float at,now=t_frame[fd->ply];
    float old_accel,old_base,old_max;
    if(fd->flags.hitlag)return;
    r->facing=fd->facing_direction;
    r->ground=!fd->phys.air_state;
    r->x=(fd->phys.air_state ? fd->phys.self_vel.X : fd->phys.self_vel_ground.X)/PM_SPEED*r->facing;
    r->y=fd->phys.self_vel.Y/PM_SPEED;
    @read_jumps@
dispatch:
    now=t_frame[fd->ply];budget=PM_JOBS;
    for(i=0;i<r->pending_count;i++) {
        r->hit_shield=r->pending[i].shield;
        PM_Run(gobj,r->pending[i].job,now);
        if(r->next)goto transfer;
    }
    r->pending_count=0;
    for(i=0;i<PM_HOOKS;i++)if(r->hooks[i].live && now>r->hooks[i].born) {
        if(r->hooks[i].until>0 && now>=r->hooks[i].until)r->hooks[i].live=0;
        else PM_Run(gobj,r->hooks[i].job,now);
        if(r->next)goto transfer;
    }
    while(budget--) {
        next=-1; at=now+1;
        for(i=0;i<r->count;i++)
            if(r->events[i].live && r->events[i].at<=now && r->events[i].at<at) {
                next=i;at=r->events[i].at;
            }
        if(next<0)break;
        r->events[next].live=0;
        PM_Run(gobj,r->events[next].job,at);
        if(r->next)goto transfer;
    }
    previous=r->trigger_order+1;
    for(;;) {
        next=-1;order=0;
        for(i=0;i<PM_TRIGGERS;i++)if(r->triggers[i].live) {
            if(r->triggers[i].until>0 && now>=r->triggers[i].until)r->triggers[i].live=0;
            else if(r->triggers[i].order<previous && r->triggers[i].order>order) {
                next=i;order=r->triggers[i].order;
            }
        }
        if(next<0)break;
        previous=order;PM_Run(gobj,r->triggers[next].job,now);
        if(r->next)goto transfer;
    }
    PM_Write(gobj,r);
    if(fd->phys.air_state) {
        fd->phys.self_vel.X=r->x*PM_SPEED*fd->facing_direction;
        fd->phys.self_vel.Y=r->y*PM_SPEED;
        Fighter_PhysAir_ApplyGravity(fd,PMMax(0,r->gravity)*PM_ACCEL,PMMax(0,r->fall)*PM_SPEED);
        if(r->drift>0) {
            old_accel=fd->attr.aerial_drift_stick_mult;
            old_base=fd->attr.aerial_drift_base;old_max=fd->attr.aerial_drift_max;
            fd->attr.aerial_drift_stick_mult=PMMax(0,r->accel)*PM_ACCEL*r->drift;
            fd->attr.aerial_drift_base=0;
            fd->attr.aerial_drift_max=PMMax(0,r->speed)*PM_SPEED*r->drift;
            Fighter_PhysAir_ApplyAerialDrift(fd);
            fd->attr.aerial_drift_stick_mult=old_accel;
            fd->attr.aerial_drift_base=old_base;fd->attr.aerial_drift_max=old_max;
        }
    }
    else {
        fd->phys.self_vel_ground.X=r->x*PM_SPEED*fd->facing_direction;
        Fighter_PhysGround_ApplyFriction(gobj);
    }
    return;
transfer:
    if(PM_Transfer(gobj,r,transitions--))goto dispatch;
}
static void PM_Landed(GOBJ *gobj)
{
    FighterData *fd=gobj->userdata;
    PortMotion *r=&port_motion[fd->ply];
    Fighter_SetGrounded2(fd);
    if(r->helpless)Fighter_EnterSpecialLanding(gobj,0,r->landing);
    else Hand_Over(gobj,PM_Form(r,fd->state_id,0));
}
void PM_Coll(GOBJ *gobj)
{
    FighterData *fd=gobj->userdata;
    PortMotion *r=&port_motion[fd->ply];
    if(!fd->phys.air_state) {
        if(!Fighter_CollGround_PassLedge(gobj)) {
            Fighter_SetAirborne(fd);Hand_Over(gobj,PM_Form(r,fd->state_id,1));
        }
    }
    else if(r->ledge>0 && fd->phys.self_vel.Y<=0)
        Fighter_CollAir_GrabFacingLedgeWalljump(gobj,0,PM_Landed);
    else if(Fighter_CollAir_IgnoreLedge_NoCB(gobj))PM_Landed(gobj);
}
'''


def build(bindings, game, length, landing, articles=None, special_entries=None, destinations=None):
    """bindings: (state id, source move id, helpless), kept independent of donor actions."""
    from echo_slapcity.gamedata import frame_of
    compiler = Compiler(articles, destinations)
    entries = []
    for state, name, helpless in bindings:
        program = game['source_programs'][name]
        schedules = []
        for entry in program.get('tl') or []:
            job = compiler.job(entry.get('a'), name)
            if job is not None:
                at = frame_of(entry) + 1
                if not math.isfinite(at) or at < 1:
                    raise ValueError(f'{name}: invalid source movement timer')
                schedules.append(f'PM_Schedule(r,{job},{number(at)});')
        entries.append(f'case {int(state)}: r->helpless={int(helpless)}; ' + ' '.join(schedules) + ' break;')
    # Each scheduled tree is acyclic. A job is scheduled at most once per entry,
    # and completed slots stay allocated until the next move, preserving order.
    if len(compiler.jobs)>512 or len(compiler.locals)>128 or compiler.contacts>64 or compiler.triggers>128:
        raise ValueError('Common movement program exceeds its bounded native capacity')
    source = expr.HELPERS.replace('Slap','PM') + inputs.HELPERS + (articles.source() if articles else '') + RUNTIME
    forms = []
    for state, name, _ in bindings:
        pair = (destinations or {}).get(name)
        if pair and min(pair) > 0:
            forms.append(f'case {state}: return air ? {pair[1]} : {pair[0]};')
    values = dict(length=number(length), capacity=max(1,len(compiler.jobs)), locals=max(1,len(compiler.locals)),
                  forms=' '.join(forms),
                  hooks=max(1,compiler.hooks), triggers=max(1,compiler.triggers),
                  read_jumps='r->jumps=fd->jump.jumps_used;r->jump_dirty=0;' if compiler.jump_resource else '',
                  write_jumps=('if(r->jump_dirty)fd->jump.jumps_used=(int)PMMax(0,PMMin(fd->attr.max_jumps,r->jumps));'
                               'r->jumps=fd->jump.jumps_used;r->jump_dirty=0;') if compiler.jump_resource else '',
                  transfer=TRANSFER if destinations else '',
                  contacts=max(1,compiler.contacts),
                  specials=','.join(str((special_entries or {}).get(name, 0))
                    for name in ('n','n_air','hi','hi_air','lw','lw_air','s','s_air')),
                  enter_special='Enter(gobj,state);' if special_entries else 'return 0;',
                  landing=number(landing), entries='\n'.join(entries),
                  jobs='\n'.join(f'case {i}: {{\n{code}\nbreak; }}' for i,code in enumerate(compiler.jobs)))
    for key,value in values.items():
        source=source.replace('@'+key+'@',str(value))
    adaptations = ['Native aggregate body and shield contacts drive source callbacks after hitlag; invincible and item contacts do not trigger them.'] if compiler.contacts else []
    adaptations += list(dict.fromkeys(compiler.adaptations))
    if destinations:
        adaptations.append('Native move transitions preserve velocity and jump resources, clear old callbacks/timers, and bound immediate transition chains to eight changes per update.')
    return source, dict(carried=compiler.carried, limits=compiler.limits, scheduled_actions=len(compiler.jobs),
                        contact_hooks=compiler.contacts, input_triggers=compiler.triggers, adaptations=adaptations)


# Negative targets are native common states; positive targets are installed specials.
TRANSFER = r'''if(budget<=0) { Leave(gobj,r->helpless,r->landing); return 0; }
    if(state>0) { Enter(gobj,state); return 1; }
    r->next=0;r->state=-1;r->hit_count=r->pending_count=r->input_mask=0;
    if(state==-3)Fighter_EnterSpecialLanding(gobj,0,r->landing);
    else if(state==-4)Fighter_EnterLanding(gobj);
    else Leave(gobj,state==-2,r->landing);'''
