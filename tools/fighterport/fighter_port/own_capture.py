"""Bounded native opponent holds for independent articles.

A successful native collision supplies the target. This adapter temporarily
owns that target's fall callbacks, permits input mashing, and yields immediately
when a hit, grab, KO, scene change or item removal interrupts the hold. It never
re-enters a hold after another state has taken control.
"""

SOURCE = r'''
typedef struct {
    GOBJ *target,*item;
    int item_kind,token,left,wiggle;
    float offset;
} PortHold;
static PortHold port_hold[12];
static void Hold_Phys(GOBJ *gobj);
static int Hold_Slot(GOBJ *gobj)
{
    int i;
    if(!gobj) return -1;
    for(i=0;i<12;i++) if(Fighter_GetSubcharGObj(i/2,i%2)==gobj) return i;
    return -1;
}
static ItemData *Hold_Item(PortHold *h)
{
    GOBJ *g;
    if(!h->item) return 0;
    for(g=(*stc_gobj_lookup)[MATCHPLINK_ITEM];g;g=g->next)
        if(g==h->item && g->userdata)
        {
            ItemData *id=g->userdata;
            if(id->kind==h->item_kind && id->item_var.var6==h->token) return id;
            return 0;
        }
    return 0;
}
static PortHold *Hold_Find(GOBJ *gobj)
{
    int slot=Hold_Slot(gobj);
    PortHold *h;
    FighterData *fd;
    if(slot<0) return 0;
    h=&port_hold[slot];fd=gobj->userdata;
    if(h->target!=gobj || !h->left) return 0;
    if(fd->state_id!=ASID_FALL || fd->cb.Phys!=Hold_Phys)
    {
        // A native hit/grab/KO already owns the new state. Leave it alone.
        h->target=0;h->left=0;h->item=0;
        return 0;
    }
    return h;
}
static void Hold_Release(GOBJ *gobj)
{
    PortHold *h=Hold_Find(gobj);
    FighterData *fd;
    if(!h) return;
    fd=gobj->userdata;h->left=0;h->target=0;h->item=0;
    fd->phys.self_vel.X=fd->phys.self_vel.Y=0;
    Fighter_EnterFall(gobj);
}
static void Hold_Anim(GOBJ *gobj)
{
    PortHold *h=Hold_Find(gobj);
    if(h && (!Hold_Item(h) || h->left<=1)) Hold_Release(gobj);
    else if(h) h->left--;
}
static void Hold_IASA(GOBJ *gobj)
{
    PortHold *h=Hold_Find(gobj);
    FighterData *fd=gobj->userdata;
    int wiggle;
    if(!h) return;
    if(fd->input.down & 0xF60) h->left-=4; // fresh buttons, including shoulder inputs
    wiggle=fd->input.lstick.X>0.5f ? 1 : fd->input.lstick.X< -0.5f ? -1 : 0;
    if(wiggle && wiggle!=h->wiggle) h->left-=3;
    h->wiggle=wiggle;
    if(h->left<=0) {h->left=1;Hold_Release(gobj);}
}
static void Hold_Phys(GOBJ *gobj)
{
    PortHold *h=Hold_Find(gobj);
    ItemData *id=h ? Hold_Item(h) : 0;
    FighterData *fd=gobj->userdata;
    if(!h) return;
    if(!id) {Hold_Release(gobj);return;}
    fd->phys.self_vel.X=fd->phys.self_vel.Y=fd->phys.self_vel.Z=0;
    fd->phys.kb_vel.X=fd->phys.kb_vel.Y=fd->phys.kb_vel.Z=0;
    fd->phys.pos.X=id->pos.X;
    fd->phys.pos.Y=id->pos.Y-h->offset;
    fd->phys.pos.Z=0;
}
static void Hold_Coll(GOBJ *gobj) {}
static int Hold_Begin(GOBJ *target,GOBJ *item,int duration,float offset)
{
    int slot=Hold_Slot(target);
    FighterData *fd;
    ItemData *id;
    PortHold *h;
    if(slot<0 || !item || !item->userdata || duration<=0) return 0;
    fd=target->userdata;id=item->userdata;
    if(fd->state_id<ASID_WAIT || fd->flags.sleep || fd->grab.attacker || fd->grab.item || Hold_Find(target)) return 0;
    h=&port_hold[slot];
    if(!fd->phys.air_state) Fighter_SetAirborne(fd);
    Fighter_EnterFall(target);
    h->target=target;h->item=item;h->item_kind=id->kind;h->token=id->item_var.var6;
    h->left=duration;h->offset=offset;h->wiggle=0;
    fd->cb.Anim=Hold_Anim;fd->cb.IASA=Hold_IASA;fd->cb.Phys=Hold_Phys;fd->cb.Coll=Hold_Coll;
    Hold_Phys(target);
    return 1;
}
static int Hold_Uses(GOBJ *target,GOBJ *item)
{
    PortHold *h=Hold_Find(target);
    return h && h->item==item && Hold_Item(h)!=0;
}
'''
