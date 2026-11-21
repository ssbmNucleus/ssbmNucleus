"""Calibrated Rivals poison on native attack starts and pending body contacts.

The shared contact observer supplies real collision records before native damage
processing. No percent-delta inference or target-character-specific state IDs.
"""
from . import own_contacts
from .oneshot import script_for

RUNTIME = r'''
typedef struct {GOBJ *target; int kind,stacks; u16 attack;} PortPoison;
static PortPoison poison[12];
static GOBJ *poison_observer;
static u16 Poison_Attack(FighterData *fd)
{
    // ft_0881.c: +206C is the stale-move attack instance. MexTK's named
    // atk_instance field is +2088 and belongs to a different combat record.
    return *(u16 *)((u8 *)fd+0x206C);
}
static int Poison_Slot(GOBJ *gobj)
{
    int i;
    for(i=0;i<12;i++) if(Fighter_GetSubcharGObj(i/2,i%2)==gobj) return i;
    return -1;
}
static PortPoison *Poison_Target(GOBJ *gobj)
{
    int i=Poison_Slot(gobj);
    FighterData *fd;
    PortPoison *p;
    if(i<0) return 0;
    fd=gobj->userdata; p=&poison[i];
    if(p->target!=gobj || p->kind!=fd->kind)
    {
        p->target=gobj;p->kind=fd->kind;p->stacks=0;p->attack=Poison_Attack(fd);
    }
    if(fd->state_id<ASID_WAIT) p->stacks=0;
    return p;
}
static void Poison_Destroy(void *data)
{
    int i;
    if(poison_observer!=data) return;
    poison_observer=0;
    for(i=0;i<12;i++){poison[i].target=0;poison[i].stacks=0;}
}
static void Poison_Frame(GOBJ *unused)
{
    int i;
    for(i=0;i<12;i++)
    {
        GOBJ *target=Fighter_GetSubcharGObj(i/2,i%2);
        FighterData *fd;
        PortPoison *p;
        u16 attack;
        if(!target){poison[i].target=0;poison[i].stacks=0;continue;}
        fd=target->userdata;p=Poison_Target(target);attack=Poison_Attack(fd);
        if(!fd->flags.sleep && p->stacks && attack!=p->attack && fd->atk_kind>=2 && fd->atk_kind<=47)
            Fighter_GiveDamage(fd,@damage@);
        p->attack=attack;
    }
}
static int Poison_DirectAmount(FighterData *fd)
{
    int action=fd->action_id,frame=(int)fd->state.frame;
    @ranges@
    return 0;
}
static int Poison_ItemAmount(GOBJ *source)
{
    int i;
    ItemData *item;
    if(!source || source->entity_class!=6 || !source->userdata) return 0;
    item=source->userdata;
    for(i=0;i<6;i++)
    {
        GOBJ *owner=contact_owners[i];
        if(!Contact_Owns(owner))continue;
        @items@
    }
    return 0;
}
static void Poison_Contact(GOBJ *source,GOBJ *target,float damage,int shield)
{
    PortPoison *attacker,*victim;
    int amount=0;
    if(shield || damage<=0 || source==target)return;
    attacker=Poison_Target(source);
    if(attacker && attacker->stacks)attacker->stacks--;
    if(Contact_Owns(source))amount=Poison_DirectAmount(source->userdata);
    else amount=Poison_ItemAmount(source);
    if(!amount)return;
    victim=Poison_Target(target);
    if(!victim || ((FighterData *)target->userdata)->state_id<ASID_WAIT)return;
    victim->stacks+=amount;
    if(victim->stacks>@cap@)victim->stacks=@cap@;
}
static void Poison_NoHit(GOBJ *a,GOBJ *b,float damage,int shield){}
static void Poison_NoHurt(GOBJ *a,GOBJ *b,float damage,int shield){}
static void Poison_Load(FighterData *fd,GOBJ *gobj)
{
    if(fd->ftaction==(FtAction *)fd->ftData->x14)return;
    Contact_Load(fd,gobj);
    if(!poison_observer)
    {
        poison_observer=GObj_Create(0,0,0);
        GObj_AddUserData(poison_observer,0,Poison_Destroy,poison_observer);
        // After all animation/IASA, before fighter physics. One native attack
        // instance survives charge/release and ground/air continuation states.
        GObj_AddProc(poison_observer,Poison_Frame,4);
    }
}
'''


def carry(mine, ctx, game, bindings, items, *, on_contact=None):
    rules=game['status_effect_rules']['Poison']
    if rules['max_stacks']!=4 or rules['attack_start_damage']!=1 or rules['remove_on_body_hit']!=1:
        raise ValueError('unsupported poison rules')
    effects={'Poison':1,'DoublePoison':2}
    ranges=set()
    for motion,stem in bindings.items():
        if motion not in ctx['action']:continue
        move=ctx['moves'].get(script_for(stem,ctx['moves'])) or {}
        for h in move.get('hitboxes') or []:
            if h.get('special_effect') in effects:
                ranges.add((ctx['action'][motion],int(h['first']),int(h['last']),effects[h['special_effect']]))
    # Larger effects first if source hit windows overlap.
    direct='\n    '.join(f'if(action=={a} && frame>={first} && frame<={last})return {n};'
                          for a,first,last,n in sorted(ranges,key=lambda row:(-row[3],row[:3])))
    projectiles=[]
    for slot,key in items.items():
        effect=game['projectiles'][key]['hit']['special_effect']
        if effect not in effects:raise ValueError('unrecognized poison item effect')
        projectiles.append(f'if(item->kind==MEX_GetFtItemID(owner,{slot}))return {effects[effect]};')
    text=RUNTIME.replace('@damage@','1.0f').replace('@cap@','4').replace('@ranges@',direct).replace('@items@','\n        '.join(projectiles))
    if on_contact is not None:
        # Validate the identifier through the same shared callback contract.
        own_contacts.source('Poison_NoHit','Poison_NoHurt',on_contact=on_contact)
        text=f'static void {on_contact}(GOBJ *,GOBJ *,float,int);\n'+text
        text=text.replace('    if(shield || damage<=0 || source==target)return;',
            f'    {on_contact}(source,target,damage,shield);\n    if(shield || damage<=0 || source==target)return;')
    mine['source']+=own_contacts.source('Poison_NoHit','Poison_NoHurt',on_contact='Poison_Contact')+text.splitlines()
    mine['load'].append('Poison_Load(fd,gobj);')
    mine['provides']+=['Poison: source hit effects add up to four stacks; normal/special attack starts cost 1%; body hits remove one stack',
        'Poison limitations: source status visuals, shield/parry contacts, projectile cleansing, and source-owner death persistence remain deferred']
    mine['numbers']['poison']=[dict(what='Calibrated action/contact rules',value=rules,**{'from':rules['source']}),
        dict(what='Native attack trigger',value='ft_0881 attack instance, normal attacks/specials/copy specials',
             **{'from':'ft_800890D0; native multi-phase continuations retain move identity'})]
    return mine
