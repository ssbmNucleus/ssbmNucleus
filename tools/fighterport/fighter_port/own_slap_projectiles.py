"""Common native projectiles from Slap's SmashProjectile data and spawn expressions.

The source program selects the spawn atomically. Melee owns contact, shields and
reflection; each instance owns its velocity, gravity, distance and lifetime.
"""
from __future__ import annotations
import math
from .own_slap_motion import number
from .own_slap_expr import Unsupported
from .own_kit import hitbox, item_code


STORAGE = r'''
typedef struct {
    int ready, age, hits, bounces, contact;
    float distance, last_x, last_y, gx, gy, travel, return_gain;
} PortProjectile;
typedef char PortProjectileFits[(sizeof(PortProjectile)<=sizeof(((ItemData *)0)->item_var))?1:-1];
static void PP_Orient(GOBJ *g)
{
    ItemData *id=g->userdata;JOBJ *model=g->hsd_object;
    // own_items already converts the mesh into world-facing item axes. Undo
    // the donor's extra quarter turn after creation and native state changes.
    model->rot.Y=id->facing_direction<0 ? 3.14159265f : 0;
    JOBJ_SetMtxDirtySub(model);
}
'''

ITEM = r'''#include "../mex.h"
@storage@
static PortProjectile *PP_Data(GOBJ *g) {return (PortProjectile *)&((ItemData *)g->userdata)->item_var;}
bool OnGiveDamage(GOBJ *g) {return @hits@>0 && ++PP_Data(g)->hits>=@hits@;}
bool OnHitShieldBounce(GOBJ *g) {return true;}
bool OnHitShieldDetermineDestroy(GOBJ *g) {return true;}
bool OnClank(GOBJ *g) {return true;}
bool OnReflect(GOBJ *g) {Item_ReflectVelocity(g);PP_Orient(g);return false;}
int Projectile_Anim(GOBJ *g)
{
    ItemData *id=g->userdata;PortProjectile *p=PP_Data(g);float x,y;
    if(Lost(g))return 1;
    if(id->state==0) {
        if(!p->ready)return ++p->age>2;
        p->age=0;p->last_x=id->pos.X;p->last_y=id->pos.Y;
        Item_SetAirborne(id);Item_ResetAllHitPlayers(id);ItemStateChange(g,1,2);PP_Orient(g);
        return 0;
    }
    x=id->pos.X-p->last_x;y=id->pos.Y-p->last_y;
    p->distance+=sqrtf(x*x+y*y);p->last_x=id->pos.X;p->last_y=id->pos.Y;
    return ++p->age>=@life@ || (@distance@>0 && p->distance>=@distance@);
}
void Projectile_Phys(GOBJ *g)
{
    ItemData *id=g->userdata;PortProjectile *p=PP_Data(g);
    if(id->state==1) {@physics@}
}
int Projectile_Coll(GOBJ *g)
{
    ItemData *id=g->userdata;PortProjectile *p=PP_Data(g);int touch,fresh;float speed,normal;
    if(id->state!=1)return 0;
    touch=Item_CollAir_NoCB(g)&@collision@;
    fresh=touch & ~p->contact;p->contact=touch;
    if(!fresh)return 0;
    if(++p->bounces>=@bounces@)return 1;
    speed=sqrtf(id->self_vel.X*id->self_vel.X+id->self_vel.Y*id->self_vel.Y);
    normal=fresh&3 ? fabsf(id->self_vel.Y) : fabsf(id->self_vel.X);
    if(speed>0 && normal/speed>@bounce_cos@)return 1;
    if(((fresh&1)&&id->self_vel.Y<0)||((fresh&2)&&id->self_vel.Y>0))id->self_vel.Y=-id->self_vel.Y;
    if(fresh&12)id->self_vel.X=-id->self_vel.X;
    id->self_vel.X*=@bounce_keep@;id->self_vel.Y*=@bounce_keep@;
    return 0;
}
__attribute__((used))
static struct ItemState item_state_table[]={
    {.state=0,.animCallback=Projectile_Anim,.physCallback=Projectile_Phys,.collCallback=Projectile_Coll},
    {.state=1,.animCallback=Projectile_Anim,.physCallback=Projectile_Phys,.collCallback=Projectile_Coll},
};
'''

# JennyFoxBoomerang.travelV is a three-phase returning projectile. Its class
# selects this adapter; all durations, directions and distances remain data.
# The source explicitly zeros yAdd.Evaluate(), so no sampled curve is missing.
RETURNING = r'''
p->travel+=1.0f/60.0f;
if(p->travel>@turn_start@+@turn_duration@) {
    p->return_gain+=1.5f/60.0f;
    id->self_vel.X=-(@speed@)*p->return_gain;id->self_vel.Y=0;
}
else if(p->travel>@turn_start@) {
    id->self_vel.X=@speed@*(1.0f-2.0f*(p->travel-@turn_start@)/@turn_duration@);
    id->self_vel.Y=@lift@;
}
else {id->self_vel.X=@speed@;id->self_vel.Y=0;}
'''

SPAWN = r'''
@storage@
static void PP_Spawn(GOBJ *gobj,int which,int bone,
    float lx,float ly,float lz,float wx,float wy,float wz,float vx,float vy,float gx,float gy)
{
    FighterData *fd=gobj->userdata;GOBJ *item;ItemData *id;PortProjectile *p;
    SpawnItem spawn={0};Vec3 local={lx,ly,lz},at;
    JOBJ_GetWorldPosition(fd->bones[bone].joint,&local,&at);
    at.X+=wx*fd->facing_direction;at.Y+=wy;at.Z=0;
    spawn.parent_gobj=gobj;spawn.parent_gobj2=gobj;
    spawn.it_kind=MEX_GetFtItemID(gobj,which);
    spawn.pos=at;spawn.pos2=at;spawn.vel.X=spawn.vel.Y=spawn.vel.Z=0;
    spawn.facing_direction=fd->facing_direction;
    spawn.damage=0;spawn.unk6=0;spawn.is_raycast_below=1;
    item=Item_CreateItem1(&spawn);if(!item)return;
    ItemStateChange(item,0,2);Item_CopyDevelopState(item,gobj);
    id=item->userdata;p=(PortProjectile *)&id->item_var;
    p->ready=1;p->age=p->hits=p->bounces=p->contact=0;
    p->distance=0;p->last_x=at.X;p->last_y=at.Y;p->gx=gx;p->gy=gy;
    p->travel=0;p->return_gain=1;
    id->self_vel.X=vx;id->self_vel.Y=vy;
    PP_Orient(item);
}
'''


class Builder:
    def __init__(self, ctx):
        self.ctx=ctx
        self.game=ctx['source_game']
        self.scale=float(ctx.get('drawn',1))
        self.length=float(self.game['unit'])*self.scale
        self.items=[]
        self.ids={}
        self.receipt=[]

    def data(self, identity):
        data=self.game.get('projectiles',{}).get(identity)
        if data:return data, 'SmashProjectile'
        article=self.game.get('articles',{}).get(identity) or {}
        if article.get('script')=='JennyFoxBoomerang':
            if float(article['travelTimeB'])<=0:
                raise Unsupported(f'article {identity}: returning projectile has no turn duration')
            return dict(article,move_vel=[article['xSpeed'],0],gravity=[0,0],deactivateAfterHits=0,
                        deactivateAfterBounces=1,deactivateAfterFrames=float(article['lifeTime'])*60), 'returning'
        raise Unsupported(f'article {identity}: custom behavior has no common projectile adapter')

    def spec(self, identity):
        if identity in self.ids:
            return self.ids[identity]
        data,kind=self.data(identity)
        model=self.game.get('article_models',{}).get(identity)
        if not model or not model.get('folder'):
            raise Unsupported(f'article {identity}: exported source model is missing')
        a=data['atkprop'];kb=self.game['kb'];mult=float(a.get('kbmult',1))
        h=dict(damage=float(a['dmg'])*float(a.get('dmgmult',1)),angle=a['angle'],
               bkb=float(a['basekb'])*float(kb['base'])*mult,
               kbg=float(a['kbgain'])*float(kb['gain'])*mult,
               fkb=float(a.get('setkb',0))*float(kb['base'])*mult,
               size=float(data['hitSize'])*float(self.game['unit']),rehit=data.get('refreshAtkFrames',0))
        from .combat_values import shield_bonus
        h['shield_damage']=shield_bonus(h['damage'],float(a.get('shielddmg',1)))
        fields=hitbox(h,self.scale)
        physics='id->self_vel.X+=p->gx;id->self_vel.Y+=p->gy;'
        if kind=='returning':
            from .own_kit import fill
            physics=fill(RETURNING,dict(turn_start=number(data['travelTimeA']),
                turn_duration=number(data['travelTimeB']),speed=number(float(data['xSpeed'])*self.length/60),
                lift=number(float(data['yChange'])/float(data['travelTimeB'])*self.length/60)))
        values=dict(storage=STORAGE,physics=physics,hits=max(0,int(data.get('deactivateAfterHits',1))),
                    bounces=max(0,int(data.get('deactivateAfterBounces',1))),
                    life=max(1,round(data.get('deactivateAfterFrames') or 600)),
                    distance=number(float(data.get('deactivateAfterDist',0))*self.length),
                    bounce_keep=number(data.get('bounceVelMult',1)),
                    bounce_cos=number(math.cos(math.radians(float(data.get('bounceAngleMin',45))))),
                    collision=0 if data.get('collidestage') is False else
                              (0 if data.get('passthroughVertical') else 3)|(0 if data.get('passthroughHorizontal') else 12))
        index=len(self.items);self.ids[identity]=index
        # Slap article prefab transforms already place their mesh in stage axes
        # (plain_mesh mirrors X). They are not fighter-local +Z weapon models.
        self.items.append(dict(name='source_'+identity.replace('-','_'),
                               model=dict(folder=model['folder'],lit=True,turn=[[1,0,0],[0,1,0],[0,0,1]]),
                               numbers=[],box=None,states=[[],[(1,fields)]],code=item_code(ITEM,values)))
        self.receipt.append(dict(id=identity,kind=kind,source_model=model['folder'],
            adaptations=['native shields/reflection and stage contact normals',
                         'maximum 600 frames when the source has no frame lifetime']))
        return index

    def spawn(self, node, context, compiler):
        identity=node.get('id')
        # The reader already resolves bone shortcuts and the model's local axes.
        candidates=[a for m in self.game.get('moves',{}).values() if m.get('slapcity_move')==context
                    for a in m.get('articles',[]) if a.get('id')==identity and a.get('bank')==node.get('b')]
        transforms={(a['bone'],tuple(a['offset']),tuple(a['world'])) for a in candidates}
        if len(transforms)!=1:
            raise Unsupported(f'article {identity}: no unambiguous source attachment')
        bone,local,world=next(iter(transforms))
        joint=self.ctx.get('joints',{}).get(bone)
        if joint is None:
            raise Unsupported(f'article {identity}: source bone {bone} is not mapped')
        data,kind=self.data(identity)
        velocity=[number(float(v)) for v in data.get('move_vel',[0,0])]
        if kind!='returning':velocity[0]=f'({velocity[0]}*r->facing)'
        gravity=[number(float(v)) for v in data.get('gravity',[0,0])]
        for entry in (node.get('g') or {}).get('md') or []:
            name=entry.get('i');value=entry.get('o') or {}
            if name in ('Velocity','Gravity'):
                if value.get('t')!='OSV2':
                    raise Unsupported(f'article {identity}: unsupported {name} initializer')
                pair=[compiler.scalar(value[axis]) for axis in ('x','y')]
                if name=='Velocity':velocity=pair
                else:gravity=pair
            elif name not in ('AttackTeam','DefendTeam','PlayerIndex'):
                raise Unsupported(f'article {identity}: unsupported initializer {name}')
        index=self.spec(identity)
        args=[str(index),str(int(joint)),*(number(v*self.scale) for v in (*local,*world)),
              *(f'({v})*PM_SPEED' for v in velocity),*(f'({v})*PM_ACCEL' for v in gravity)]
        return 'PP_Spawn(gobj,'+', '.join(args)+');'

    def source(self):
        return SPAWN.replace('@storage@',STORAGE) if self.items else ''

    def load(self):
        if not self.items:return []
        return ['{ ItemDesc **items=fd->ftData->items; int i;',
                f'for(i=0;items && i<{len(self.items)};i++)if(items[i])MEX_IndexFighterItem(fd->kind,items[i],i); }}']
