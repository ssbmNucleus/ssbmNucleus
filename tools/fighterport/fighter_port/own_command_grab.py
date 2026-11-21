"""Native command-grab primitives shared by custom special adapters.

Collision, ownership and thrown damage remain Melee's. The adapter supplies its
own hold state/animation, finite release time and interruption cleanup. The
common pulled state follows an anchor joint and works with airborne victims.
"""

SOURCE=r'''
#define NG_PULL_OWNER ((void (*)(GOBJ *))0x800D9CE8)
#define NG_PULL_TARGET ((void (*)(GOBJ *,GOBJ *))0x800DAADC)
#define NG_HIT_NEW ((void (*)(FighterData *,ftHit *))0x800768A0)
#define NG_HIT_DAMAGE ((void (*)(ftHit *,int,GOBJ *))0x8007ABD0)
#define NG_HIT_ANGLE ((void (*)(ftHit *,int,GOBJ *))0x8007AC9C)
#define NG_HIT_PLACE ((void (*)(FighterData *,ftHit *))0x8007AD18)
#define NG_HIT_AFTER ((void (*)(FighterData *))0x80080484)
static int NativeGrab_Live(GOBJ *candidate)
{
    int p,s;
    if(!candidate)return 0;
    for(p=0;p<6;p++)for(s=0;s<2;s++)
        if(Fighter_GetSubcharGObj(p,s)==candidate)return 1;
    return 0;
}
static GOBJ *NativeGrab_Target(GOBJ *owner)
{
    FighterData *fd=owner->userdata,*target;
    GOBJ *other=fd->grab.attacker;
    if(!NativeGrab_Live(other))return 0;
    target=other->userdata;
    if(target->grab.attacker!=owner || target->flags.dead || target->flags.sleep)return 0;
    return other;
}
static void NativeGrab_Box(GOBJ *gobj,int slot,const float *b)
{
    FighterData *fd=gobj->userdata;
    ftHit *h=&fd->hitbox[slot];
    if(!h->active || h->x4)
    {h->x4=0;h->active=1;fd->flags.hitbox_active=1;NG_HIT_NEW(fd,h);}
    h->bone=fd->bones[0].joint;
    NG_HIT_DAMAGE(h,0,gobj);NG_HIT_ANGLE(h,0,gobj);
    h->offset.X=b[0];h->offset.Y=b[1];h->offset.Z=b[2];h->size=b[3];
    h->kb_growth=h->wdsk=h->kb=0;h->attribute=8;h->shield_dmg=0;
    h->hitsound_severity=h->hitsound_kind=0;h->x40=0x30;h->x41=0;
    *((u8 *)h+0x42)=0x45;*((u8 *)h+0x43)&=(u8)~0x20;
    NG_HIT_PLACE(fd,h);NG_HIT_AFTER(fd);
}
static void NativeGrab_Owner(GOBJ *gobj,int state,int anchor)
{
    FighterData *fd=gobj->userdata;
    // Common setup establishes ownership/attachment bookkeeping. Replace only
    // its pull animation with the adapter's hold, preserving throw bookkeeping.
    NG_PULL_OWNER(gobj);
    ActionStateChange(0,1,0,gobj,state,0x4000,0);
    fd->state_var.state_var7=(int)fd->bones[anchor].joint; // native capturedamage.x18
    Fighter_AdvanceScript(gobj);
    fd->phys.self_vel.X=fd->phys.self_vel.Y=fd->phys.self_vel_ground.X=0;
}
static void NativeGrab_Victim(GOBJ *victim,GOBJ *owner)
{
    FighterData *fd=victim->userdata;
    Fighter_SetAirborne(fd);
    NG_PULL_TARGET(victim,owner);
}
static int NativeGrab_Throw(GOBJ *owner,int damage,int angle,int growth,int base,int fixed)
{
    FighterData *fd=owner->userdata;
    GOBJ *victim=NativeGrab_Target(owner);
    ftHit zero={0},*h=&fd->throw_hitbox[0];
    if(!victim)return 0;
    *h=zero;NG_HIT_DAMAGE(h,damage,owner);NG_HIT_ANGLE(h,angle,owner);
    h->kb_growth=growth;h->kb=base;h->wdsk=fixed;
    Fighter_ThrownRelease_UpdateUnk(owner,victim);
    Fighter_ThrownApplyKnockback(victim,owner,0);
    return 1;
}
static void NativeGrab_Drop(GOBJ *owner)
{
    GOBJ *victim=NativeGrab_Target(owner);
    FighterData *target;
    if(!victim)return;
    target=victim->userdata;
    // An external hit/grab is authoritative; never replace its damage state.
    if(target->state_id!=ASID_CAPTUREPULLEDHI && target->state_id!=ASID_CAPTUREPULLEDLW)return;
    Fighter_BreakGrab(owner,victim);Fighter_EnterFall(victim);
}
'''
