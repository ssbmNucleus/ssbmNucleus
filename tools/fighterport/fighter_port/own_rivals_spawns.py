"""Schedule supported articles from common Rivals states.

Window declarations are automatic. Compiled triggers need a named policy whose
adaptation is carried in the package; no class is spawned merely because it exists.
"""
from . import own_rivals_articles as articles
from .own_slap_motion import number


def policy(game, move, creation):
    if creation.get('real') is not None:
        return int(creation['real']), {}, []
    if (game.get('fighter') == 'loxodont' and move.get('rivals2_attack') == 'Nspecial'
            and creation['id'] == 'moltenboulder'):
        first = next((int(at) for at,name,length in move.get('windows') or []
                      if name in ('Active Ground','Active Air')), None)
        if first is None:raise articles.Unsupported('boulder path has no active release window')
        return first, dict(collision={k:'Destroy' for k in
            ('GroundCollisionResponse','WallCollisionResponse','CeilingCollisionResponse')},on_hit='Destroy',max_life=180,compiled_adapter=True), [
            'Loxodont compiled release: one boulder at the active window, with source launch/gravity and source model',
            'boulder adaptation: single contact; stage impact removes it; magma pools, charge scaling and batting are not carried']
    raise articles.Unsupported('compiled article creation needs a named mechanic policy')


def build(ctx, bindings):
    game=ctx['source_game'];drawn=float(ctx.get('drawn',1))
    items,by_key,events,carried,limits,adaptations=[],{},[],[],[],[]
    marks={}
    for state,action,move,helpless in bindings:
        for creation in move.get('articles') or []:
            identity=creation['id'];label=f'{move.get("rivals2_attack")}/{identity}'
            try:
                first,options,notes=policy(game,move,creation)
                declaration=creation.get('source_creation') or {}
                if set(declaration)-{'ArticleData','CreationWindowStringTableKey','CreationWindowFrame',
                                     'InitialOffsetFromOwner','InitialFacingMultiplier','ArticleInitialWindowStringTableKey'}:
                    raise articles.Unsupported('unknown source creation options')
                facing=float(declaration.get('InitialFacingMultiplier',1))
                if facing not in (-1,1):raise articles.Unsupported('non-cardinal initial facing')
                entry=declaration.get('ArticleInitialWindowStringTableKey')
                if not entry:raise articles.Unsupported('article initial window is unknown')
                data=(game.get('projectiles') or {}).get(identity)
                model=(game.get('article_models') or {}).get(identity)
                if not data or not model:raise articles.Unsupported('source article program or exported model is missing')
                offset=creation.get('offset')
                if not offset or len(offset)!=2 or first<1:raise articles.Unsupported('source article placement or time is invalid')
                mark=(move.get('rivals2_attack'),identity,creation.get('window') or 'compiled',
                      declaration.get('CreationWindowFrame',0),tuple(offset),facing,entry)
                if mark not in marks and len(marks)>=32:raise articles.Unsupported('more than 32 article casts in one move')
                key=(identity,entry,str(sorted(options.items())))
                if key not in by_key:
                    item_name=identity if not any(k[0]==identity for k in by_key) else f'{identity}_{len(items)}'
                    item,receipt=articles.build(data,item_name,dict(folder=model['folder']),drawn,entry=entry,**options)
                    by_key[key]=len(items);items.append(item);carried.append(receipt)
                    adaptations.extend(notes+model.get('adaptations',[]))
                index=by_key[key]
                # Ground/air forms and release branches share the same logical cast.
                if mark not in marks:marks[mark]=len(marks)
                bottom=float((model.get('bounds') or [[0,0,0]])[0][1])*drawn
                events.append((state,first,marks[mark],index,float(offset[0]),float(offset[1]),facing,max(0,-bottom)+.05))
            except articles.Unsupported as exc:
                limits.append(f'{label}: {exc}')
    cases=[]
    for state,first,mark,index,x,y,facing,clearance in events:
        cases.append(f'if(fd->state_id=={state} && t_frame[fd->ply]=={first} && !(rp_fired[fd->ply] & (1u<<{mark}))) {{'
            f' rp_fired[fd->ply]|=1u<<{mark};RP_Spawn(gobj,{index},{number(x)},{number(y)},{number(facing)},{number(clearance)}); }}')
    source=RUNTIME.replace('@events@','\n'.join(cases)) if items else ''
    load=['rp_fired[fd->ply]=0;','{ ItemDesc **items=fd->ftData->items; int i;',
          f'for(i=0;items && i<{len(items)};i++)if(items[i])MEX_IndexFighterItem(fd->kind,items[i],i); }}'] if items else []
    return source,items,load,dict(carried=carried,limits=list(dict.fromkeys(limits)),adaptations=list(dict.fromkeys(adaptations)))


RUNTIME=r'''
static void RP_Spawn(GOBJ *gobj,int which,float x,float y,float facing,float clearance){
    FighterData *fd=gobj->userdata;GOBJ *item;ItemData *id;SpawnItem spawn={0};
    spawn.parent_gobj=gobj;spawn.parent_gobj2=gobj;spawn.it_kind=MEX_GetFtItemID(gobj,which);
    spawn.pos=fd->phys.pos;spawn.pos.X+=x*fd->facing_direction;
    if(!fd->phys.air_state && y<clearance)y=clearance;
    spawn.pos.Y+=y;spawn.pos.Z=0;spawn.pos2=spawn.pos;
    spawn.facing_direction=fd->facing_direction*facing;spawn.is_raycast_below=1;
    item=Item_CreateItem1(&spawn);if(!item)return;
    ItemStateChange(item,0,2);Item_CopyDevelopState(item,gobj);
    id=item->userdata;id->item_var.var1=1;
}
void RP_Phys(GOBJ *gobj){
    FighterData *fd=gobj->userdata;
    if(!fd->flags.hitlag){@events@}
    RV_Phys(gobj);
}
'''
