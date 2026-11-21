"""Declared Rivals special grabs, using native collision and reciprocal capture.

Only explicit OnGrab paths with a finite declared throw release are executable.
Compiled capture predicates and article swallowing still need their own adapters.
"""
import math
from . import own_command_grab
from .own_kit import fill


def declaration(game, move, event):
    condition=event['condition']
    if (condition.get('WindowCancelType','').split('::')[-1]!='OnGrab'
            or condition.get('WindowCancelPrerequisite','::None').split('::')[-1]!='None'
            or condition.get('NegatePrerequisite') or condition.get('bPreseveWindowTimer')
            or condition.get('CancelIntoAttack','::None').split('::')[-1]!='None'):
        raise ValueError('guarded/compiled grab transition needs an adapter')
    if not any(o.get('cmd')=='CATCH' for o in move.get('other') or []):
        raise ValueError('OnGrab has no exported native grab geometry')
    attack=(game.get('source_attacks') or {}).get(move.get('rivals2_attack')) or {}
    windows={w['StringTableKey']:w for w in attack.get('Windows') or []}
    target=condition.get('PostCancelWindowStringTableKey')
    path={};at=1;current=target
    while current and current not in path and current in windows:
        window=windows[current];length=int(window.get('WindowLengthFrames',0))
        if length<=0 or length>600:
            raise ValueError('grab path has no finite source duration')
        path[current]=at;at+=length;current=window.get('NextWindowStringTableKey')
    releases=[r for r in (attack.get('ThrowData') or {}).get('ThrowReleaseData') or []
              if r.get('ReleaseWindowStringTableKey') in path]
    if len(releases)!=1:
        raise ValueError('grab needs one declared throw release on its capture path')
    release=releases[0];frame=path[release['ReleaseWindowStringTableKey']]
    if not 1<frame<=300:
        raise ValueError('capture duration is outside the bounded native hold')
    if any(windows[name].get('WindowCancels') for name,start in path.items() if start<frame):
        raise ValueError('conditional capture before release needs an adapter')
    knockback=release.get('ThrowKnockbackData') or {}
    required=('Damage','BaseKnockback','KnockbackScaling','KnockbackAngle')
    if any(not isinstance(knockback.get(k),(int,float)) or not math.isfinite(knockback[k]) for k in required):
        raise ValueError('grab release has incomplete throw damage/knockback')
    return dict(target=target,release=frame,release_window=release['ReleaseWindowStringTableKey'],
                knockback=knockback,source_release=release)


SOURCE=r'''
typedef struct {
    int launch,hold,hold_ground,hold_air,release_ground,release_air,first,last,release,anchor,count;
    int damage,angle,growth,base;
    float balls[4][4];
} RGSpec;
typedef struct {int spec,active,holding,boxes;} RGState;
static RGState rg_state[6];
static int RG_IsHolding(GOBJ *gobj){FighterData *fd=gobj->userdata;return rg_state[fd->ply].holding;}
static const RGSpec rg_specs[@count@]={@specs@};
static void RG_Caught(GOBJ *gobj)
{
    FighterData *fd=gobj->userdata;RGState *r=&rg_state[fd->ply];const RGSpec *s;
    if(!r->active || r->spec<0 || r->spec>=@count@)return;
    s=&rg_specs[r->spec];
    NativeGrab_Owner(gobj,s->hold,s->anchor);
    t_frame[fd->ply]=1;r->holding=1;r->boxes=0;
}
static int RG_Find(int state)
{
    int i;for(i=0;i<@count@;i++)if(rg_specs[i].launch==state)return i;
    return -1;
}
static void RG_Enter(GOBJ *gobj)
{
    FighterData *fd=gobj->userdata;RGState *r=&rg_state[fd->ply];int index=RG_Find(fd->state_id);
    if(r->holding)NativeGrab_Drop(gobj);
    r->spec=index;r->active=index>=0;r->holding=r->boxes=0;
    if(index>=0)Fighter_InitGrab(fd,1,RG_Caught,0,NativeGrab_Victim);
}
static void RG_Frame(FighterData *fd,GOBJ *gobj)
{
    RGState *r=&rg_state[fd->ply];const RGSpec *s;int index;
    if(!r->active)return;
    s=&rg_specs[r->spec];
    if(r->holding) {
        if(fd->flags.dead || fd->flags.sleep ||
           (fd->state_id!=s->hold_ground && fd->state_id!=s->hold_air &&
            fd->state_id!=s->release_ground && fd->state_id!=s->release_air)) {
            NativeGrab_Drop(gobj);r->active=r->holding=r->boxes=0;
        }
        else if(!NativeGrab_Target(gobj))r->holding=0;
    }
    else {
        index=RG_Find(fd->state_id);
        if(index>=0 && index!=r->spec)RG_Enter(gobj);
        else if(index<0)r->active=r->boxes=0;
    }
}
static void RG_Load(FighterData *fd){RGState zero={0};rg_state[fd->ply]=zero;rg_state[fd->ply].spec=-1;}
void RG_Anim(GOBJ *gobj)
{
    FighterData *fd=gobj->userdata;RGState *r=&rg_state[fd->ply];const RGSpec *s;int frame,i;
    if(fd->flags.hitlag)return;
    RG_Frame(fd,gobj);RV_Anim(gobj);RG_Frame(fd,gobj);
    if(!r->active)return;
    s=&rg_specs[r->spec];frame=t_frame[fd->ply];
    if(r->holding) {
        if(frame>=s->release && (fd->state_id==s->release_ground || fd->state_id==s->release_air)) {
            NativeGrab_Throw(gobj,s->damage,s->angle,s->growth,s->base,0);
            r->holding=0;
        }
    }
    else if(fd->state_id==s->launch) {
        if(frame>=s->first && frame<s->last) {
            for(i=0;i<s->count;i++)NativeGrab_Box(gobj,i,s->balls[i]);
            r->boxes=1;
        }
        else if(r->boxes){Fighter_HitboxDisableAll(gobj);r->boxes=0;}
    }
}
void RG_IASA(GOBJ *gobj)
{
    FighterData *fd=gobj->userdata;
    if(!rg_state[fd->ply].holding)RV_IASA(gobj);
}
void RG_Phys(GOBJ *gobj)
{
    FighterData *fd=gobj->userdata;
    @physics@(gobj);
    if(rg_state[fd->ply].holding)
        fd->phys.self_vel.X=fd->phys.self_vel.Y=fd->phys.self_vel_ground.X=0;
}
void RG_Coll(GOBJ *gobj)
{
    FighterData *fd=gobj->userdata;
    if(!rg_state[fd->ply].holding)RV_Coll(gobj);
}
'''


def build(ctx, rows, bindings, physics='RV_Phys'):
    from .oneshot import grab_boxes
    from echo_rivals2.gamedata import melee_kb,angle_of
    game=ctx['source_game'];scale=float(ctx.get('drawn',1));specs=[];carried=[];limits=[]
    flags={ctx['first']+i:row['flags'] for i,row in enumerate(rows)}
    for state,action,move,helpless in bindings:
        events=[e for e in move.get('window_cancels') or []
                if e['condition'].get('WindowCancelType','').endswith('::OnGrab')]
        if not events:continue
        if len(events)!=1:
            limits.append(f'{move.get("rivals2_attack")}: multiple grab destinations need an adapter');continue
        try:
            declared=declaration(game,move,events[0])
        except ValueError as exc:
            limits.append(f'{move.get("rivals2_attack")}: {exc}');continue
        holds=[(s,m) for s,_,m,_ in bindings if m.get('rivals2_attack')==move.get('rivals2_attack')
               and m.get('windows') and m['windows'][0][1]==declared['target']]
        if not holds:
            limits.append(f'{move.get("rivals2_attack")}: capture destination is not installed');continue
        hold=next((s for s,m in holds if flags[s]==flags[state]),None)
        if hold is None:
            raise ValueError('declared grab has no matching ground/air capture state')
        releases=[(s,m) for s,_,m,_ in bindings if m.get('rivals2_attack')==move.get('rivals2_attack')
                  and any(w[1]==declared['release_window'] for w in m.get('windows') or [])]
        release_state=next((s for s,m in releases if flags[s]==flags[state]),None)
        if release_state is None:
            raise ValueError('declared grab release has no built ground/air phase')
        release_move=next(m for s,m in releases if s==release_state)
        release_frame=next(w[0] for w in release_move['windows'] if w[1]==declared['release_window'])
        geometry=grab_boxes(move,scale)
        if geometry is None:
            raise ValueError('declared grab geometry must be normalized to top by the reader')
        first,last,balls=geometry
        first=max(first,int(events[0]['first']));last=min(last,int(events[0]['last'])+1)
        if not 0<first<last or not 1<=len(balls)<=4:
            raise ValueError('declared special grab has invalid active geometry/window')
        hit=next(o for o in move['other'] if o['cmd']=='CATCH')
        bone=hit.get('from_bone')
        if bone and bone not in ctx['joints']:
            raise ValueError(f'capture anchor {bone} is missing from the native skeleton')
        anchor=ctx['joints'][bone] if bone else 0
        k=declared['knockback'];damage=round(k['Damage']);base,growth=melee_kb(k['BaseKnockback'],k['KnockbackScaling'],k['Damage'])
        ground=next((s for s,m in holds if not flags[s]&0x400),hold)
        air=next((s for s,m in holds if flags[s]&0x400),hold)
        release_ground=next((s for s,m in releases if not flags[s]&0x400),release_state)
        release_air=next((s for s,m in releases if flags[s]&0x400),release_state)
        values=[state,hold,ground,air,release_ground,release_air,first,last,release_frame,anchor,len(balls),
                damage,round(angle_of(k['KnockbackAngle'])),round(growth),round(base)]
        ball_rows=','.join('{'+','.join(repr(float(v))+'f' for v in b['position']+[b['radius']])+'}' for b in balls)
        specs.append('{'+','.join(str(int(v)) for v in values)+',{'+ball_rows+'}}')
        carried.append(dict(source=move['rivals2_attack'],state=state,capture_state=hold,
                            first=first,last=last,release=declared['release'],release_state=release_state,
                            release_frame=release_frame,damage=damage))
    if not specs:return '',dict(carried=[],limits=limits,adaptations=[])
    adaptations=['Native reciprocal capture uses the first source grab bone and Melee captured pose; source thrown animation and release offset are not reproduced.',
                 'Owner movement and landing are suspended during the finite hold; damage interruption releases the opponent safely.',
                 'Native throw damage, knockback, stale moves and stage interactions replace source tech/DI modifiers.']
    source=own_command_grab.SOURCE+'\n'+fill(SOURCE,dict(count=len(specs),specs=',\n'.join(specs),physics=physics))
    return source,dict(carried=carried,limits=limits,adaptations=adaptations)
