"""Native article phases shared by Rivals adapters.

Callers select the entry phase and provide the rendered model. Compiled creation,
capture and collision behavior needs an explicit adapter, never an inferred spawn.
"""
from .own_kit import hitbox, item_code
from .own_slap_motion import number


class Unsupported(ValueError):
    pass


def plan(data, entry, terminals=('Destroy', 'Captured')):
    program = data.get('program') or {}
    phases = program.get('phases') or []
    names = [p['name'] for p in phases]
    if program.get('schema') != 1 or len(set(names)) != len(names):
        raise Unsupported('article requires a complete, unambiguous phase program')
    by_name = {p['name']: p for p in phases}
    result, seen = [], set()
    current = entry
    while current and current not in terminals and current not in seen:
        if current not in by_name:
            raise Unsupported(f'article phase {current!r} is missing')
        phase = by_name[current]
        if not 0 < phase['length'] <= 65535:
            raise Unsupported(f'article phase {current!r} has no bounded duration')
        seen.add(current);result.append(phase)
        current = phase['next']
    if not result or len(result) > 32:
        raise Unsupported('article requires 1..32 reachable phases')
    return result, current in seen


def scripts(phases, drawn, status_effects=()):
    states = [[(0, None)]]
    for phase in phases:
        hits = phase['hits']
        spans = {(h['first'], min(phase['length'], h['first']+h['length'])) for h in hits}
        if len(hits) > 4 or len(spans) > 1:
            raise Unsupported('article needs at most four simultaneous hitboxes with shared activation times')
        events = []
        for index, active in enumerate(hits):
            h = active['hit']; a = active['attribute'] or {}
            if h is None:
                raise Unsupported(f'article hit {active["name"]!r} has compiled contact behavior')
            if a.get('BoneName', 'Root') not in ('Root', 'None', '') or a.get('OffsetBoneName', 'None') != 'None' \
                    or a.get('InitialInterpolationMode', 'None').split('::')[-1] != 'None':
                raise Unsupported('article hitbox requires an animated source bone')
            if a.get('HitResponse', 'Hit').split('::')[-1] != 'Hit' \
                    or a.get('Groundedness', 'GroundOrAir').split('::')[-1] != 'GroundOrAir':
                raise Unsupported('article grab or groundedness requires an adapter')
            if h.get('special_effect') not in (None, '', 'None', *status_effects):
                raise Unsupported(f'article status {h["special_effect"]!r} requires an adapter')
            if any(h.get('offset') or [0, 0, 0]):
                raise Unsupported('article nonzero skeletal hit offsets require a model-space adapter')
            if not 0 <= active['first'] < phase['length'] or active['length'] <= 0:
                raise Unsupported('article hit interval lies outside its phase')
            events.append((active['first'], hitbox(h, drawn, id=index, group=0)))
        if spans:
            end = next(iter(spans))[1]
            if end < phase['length']:
                events.append((end, None))
        states.append(events or [(0, None)])
    return states


def continuity(phases, states):
    """Keep an unchanged full-phase hit alive without resetting its victim list."""
    keep = [0]*len(phases)
    for index, phase in enumerate(phases):
        if phase['refresh'] or not phase['hits']:
            continue
        incoming = [p for p in phases if p['next'] == phase['name']]
        if not incoming:  # The caller creates a fresh article at this entry.
            continue
        def full(p):
            return all(h['first'] == 0 and h['length'] >= p['length'] for h in p['hits'])
        def shape(p):
            return [(h['name'],h['hit'],h['attribute'],h['properties']) for h in p['hits']]
        if index == 0 or not full(phase) or any(not full(p) or shape(p)!=shape(phase) for p in incoming):
            raise Unsupported('article hit memory changes across phases; requires an adapter')
        keep[index]=1
        states[index+1]=[]  # KEEP_HIT carries the existing boxes; do not recreate them.
    return keep


def physics(phase):
    text = [f'if(id->self_vel.Y>-{number(phase["max_fall"])}) {{ id->self_vel.Y-={number(phase["gravity"])}; '
            f'if(id->self_vel.Y<-{number(phase["max_fall"])})id->self_vel.Y=-{number(phase["max_fall"])}; }}']
    friction = number(phase['friction_air'])
    text.append(f'if(id->self_vel.X>0){{id->self_vel.X-={friction};if(id->self_vel.X<0)id->self_vel.X=0;}}'
                f'else if(id->self_vel.X<0){{id->self_vel.X+={friction};if(id->self_vel.X>0)id->self_vel.X=0;}}')
    for velocity in phase['velocities']:
        if velocity['modifiers']:
            raise Unsupported('article velocity modifier requires an adapter')
        for axis, kind, value in zip('XY', velocity['kinds'], velocity['values']):
            if kind in ('', 'None'):
                continue
            operation = {'SetVelocity': '=', 'ConstVelocity': '=', 'AddVelocity': '+=', 'MultiplyVelocity': '*='}.get(kind)
            if operation is None:
                raise Unsupported(f'article velocity operation {kind!r}')
            at = int(velocity['first']); last = min(int(velocity['last']), phase['length']-1)
            if not 0 <= at <= last:
                raise Unsupported('article velocity interval lies outside its phase')
            condition = f'p->frame>={at} && p->frame<={last}' if kind == 'ConstVelocity' else f'p->frame=={at}'
            val = number(value)
            if kind != 'MultiplyVelocity':
                val += '*p->speed'
                if axis == 'X': val += '*p->facing'
            text.append(f'if({condition})id->self_vel.{axis}{operation}{val};')
    return ''.join(text)


RUNTIME = r'''#include "../mex.h"
typedef struct {int ready,frame,age;float facing,speed;} RivalsArticle;
typedef char RivalsArticleFits[(sizeof(RivalsArticle)<=sizeof(((ItemData *)0)->item_var))?1:-1];
static RivalsArticle *RA_Data(GOBJ *g){return (RivalsArticle *)&((ItemData *)g->userdata)->item_var;}
static const int ra_lengths[]={0,@lengths@};
static const int ra_next[]={0,@next@};
static const int ra_keep[]={0,@keep@};
static void RA_Enter(GOBJ *g,int state){
    ItemData *id=g->userdata;RivalsArticle *p=RA_Data(g);p->frame=0;
    if(ra_keep[state]){if(id->state!=state)ItemStateChange(g,state,2|0x10);}
    else {Item_ResetAllHitPlayers(id);ItemStateChange(g,state,2);}
}
bool OnGiveDamage(GOBJ *g){return @hit_destroy@;}
bool OnHitShieldBounce(GOBJ *g){return true;}
bool OnHitShieldDetermineDestroy(GOBJ *g){return true;}
bool OnClank(GOBJ *g){return true;}
bool OnReflect(GOBJ *g){
    ItemData *id=g->userdata;RivalsArticle *p=RA_Data(g);
    float before=sqrtf(id->self_vel.X*id->self_vel.X+id->self_vel.Y*id->self_vel.Y),after;
    Item_ReflectVelocity(g);
    after=sqrtf(id->self_vel.X*id->self_vel.X+id->self_vel.Y*id->self_vel.Y);
    if(before>0.00001f)p->speed*=after/before;
    p->facing=id->facing_direction;
    return false;
}
int RA_Anim(GOBJ *g){
    ItemData *id=g->userdata;RivalsArticle *p=RA_Data(g);int next;
    if(Lost(g))return 1;
    if(id->is_hitlag)return 0;
    if(!id->state){
        if(!p->ready)return ++p->age>2;
        p->age=0;p->facing=id->facing_direction;p->speed=1;
        Item_SetAirborne(id);RA_Enter(g,1);return 0;
    }
    if(++p->age>=@max_life@)return 1;
    if(++p->frame>=ra_lengths[id->state]){
        next=ra_next[id->state];if(!next)return 1;
        RA_Enter(g,next);
    }
    return 0;
}
void RA_Phys(GOBJ *g){
    ItemData *id=g->userdata;RivalsArticle *p=RA_Data(g);
    if(id->is_hitlag)return;
    switch(id->state){@physics@}
}
int RA_Coll(GOBJ *g){
    ItemData *id=g->userdata;
    return id->state && (Item_CollAir_NoCB(g)&@collision@)!=0;
}
__attribute__((used)) static struct ItemState item_state_table[]={@rows@};
'''


def build(data, name, model, drawn, *, entry, max_life=600, collision=None, on_hit=None, status_effects=(), compiled_adapter=False):
    if data.get('class') and not compiled_adapter:
        raise Unsupported(f'compiled article class {data["class"]!r} requires an explicit adapter')
    phases, loop = plan(data, entry)
    states = scripts(phases, drawn, status_effects)
    keep = continuity(phases, states)
    ends = data.get('ends') or {}
    collision = ends if collision is None else collision
    mask = 0
    for key, bits in [('GroundCollisionResponse', 1), ('CeilingCollisionResponse', 2), ('WallCollisionResponse', 12)]:
        reaction = collision.get(key, '')
        if reaction == 'Destroy': mask |= bits
        elif reaction != 'None': raise Unsupported(f'article {key}={reaction!r} requires an adapter')
    hit_reaction = ends.get('HasHitReaction', '') if on_hit is None else on_hit
    if hit_reaction not in ('Destroy', 'None'):
        raise Unsupported(f'article hit reaction {hit_reaction!r} requires an adapter')
    if not 0 < max_life <= 65535:
        raise ValueError('article maximum lifetime must be 1..65535')
    indexes = {p['name']: i+1 for i,p in enumerate(phases)}
    values = dict(lengths=','.join(str(p['length']) for p in phases),
        keep=','.join(map(str,keep)),
        next=','.join(str(indexes.get(p['next'], 0)) for p in phases),
        physics=''.join(f'case {i+1}: {physics(p)} break;' for i,p in enumerate(phases)),
        hit_destroy=1 if hit_reaction == 'Destroy' else 0, collision=mask, max_life=max_life,
        rows=','.join(f'{{.state={i},.animCallback=RA_Anim,.physCallback=RA_Phys,.collCallback=RA_Coll}}'
                     for i in range(len(phases)+1)))
    item = dict(name=name, model=model, numbers=[0.0], states=states, code=item_code(RUNTIME, values))
    receipt = dict(id=name, entry=entry, phases=[p['name'] for p in phases], loop=loop,
        max_life=max_life, adaptations=['native shield/clank/reflection; owner-loss and blast-zone cleanup',
            'terminal Destroy/Captured remove the native item; separate visual tails are omitted'])
    return item, receipt
