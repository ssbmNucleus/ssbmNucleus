"""Observe pending native fighter contacts after collision and before damage application.

The ordinary OnGiveDamage callback is skipped when the same fighter takes damage
on that update. Observing the collision records avoids that lost trade and sees
armored damage without inventing an event from a later percent change.
"""
import re

RUNTIME = '''
static void @hit@(GOBJ *,GOBJ *,float,int);
static void @hurt@(GOBJ *,GOBJ *,float,int);
// Fighter_Create uses p_link 8. HSD orders processes by priority then p_link.
// This helper runs at p_link 0 / priority 14: after ALL collision (13), before fighter damage/reset (14).
typedef struct {GOBJ *source,*target; float damage; int shield;} PortContact;
static GOBJ *contact_observer;
static GOBJ *contact_owners[6];
static int contact_kinds[6];
static int Contact_Owns(GOBJ *gobj)
{
    int i;
    for (i = 0; i < 6; i++)
        if (gobj && contact_owners[i] == gobj && Fighter_GetGObj(i) == gobj &&
            ((FighterData *)gobj->userdata)->kind == contact_kinds[i])
            return 1;
    return 0;
}
static void Contact_Destroy(void *data)
{
    int i;
    if (contact_observer == data)
    {
        contact_observer = 0;
        for (i = 0; i < 6; i++)
            contact_owners[i] = 0;
    }
}
static void Contact_Observe(GOBJ *unused)
{
    PortContact events[24];
    int i,count = 0;
    // Snapshot all records first: callbacks may update resources but must not alter the engine's damage
    // fields or change action state here. Queue any resulting state transition for a later IASA update.
    for (i = 0; i < 12; i++)
    {
        GOBJ *target = Fighter_GetSubcharGObj(i / 2,i % 2);
        FighterData *fd;
        if (!target)
            continue;
        fd = target->userdata;
        if (fd->flags.sleep)
            continue; // the native damage process also skips sleeping fighters and its reset
        if (fd->dmg.percent_temp > 0.0f && fd->dmg.hit_log.source &&
            (fd->dmg.tip_force_applied == 0.0f || fd->dmg.hit_log.force_applied > 0.0f))
        {
            events[count].source = fd->dmg.hit_log.source;
            events[count].target = target;
            events[count].damage = fd->dmg.percent_temp;
            events[count++].shield = 0;
        }
        if (fd->shield.dmg_taken2 > 0 && fd->shield.dmg_source)
        {
            events[count].source = fd->shield.dmg_source;
            events[count].target = target;
            events[count].damage = fd->shield.dmg_taken2;
            events[count++].shield = 1;
        }
    }
    for (i = 0; i < count; i++)
    {
        PortContact *e = &events[i];
        if (Contact_Owns(e->source))
            @hit@(e->source,e->target,e->damage,e->shield);
        if (Contact_Owns(e->target))
            @hurt@(e->target,e->source,e->damage,e->shield);
    }
}
static void Contact_Load(FighterData *fd,GOBJ *gobj)
{
    contact_owners[fd->ply] = gobj;
    contact_kinds[fd->ply] = fd->kind;
    if (!contact_observer)
    {
        contact_observer = GObj_Create(0,0,0);
        GObj_AddUserData(contact_observer,0,Contact_Destroy,contact_observer);
        GObj_AddProc(contact_observer,Contact_Observe,FTPRI_DMGAPPLY);
    }
}
'''


def source(on_hit, on_hurt, *, on_contact=None):
    """Callbacks receive owner, other GObj, pending damage, and a shield flag.

    Optional on_contact receives every raw source/target pair, including items and
    fighters that are not registered owners. This supports statuses on opponents.

    These are native per-defender update records. Melee aggregates simultaneous damage
    and keeps its selected source, and keeps only the strongest shield hit. Do not claim
    this is a full log of every hitbox/victim pair. Phantom-only contacts are excluded.
    """
    if not all(re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*',name) for name in (on_hit,on_hurt,*([on_contact] if on_contact is not None else []))):
        raise ValueError('contact callbacks must be C identifiers')
    text=RUNTIME.replace('@hit@',on_hit).replace('@hurt@',on_hurt)
    if on_contact is not None:
        text=f'static void {on_contact}(GOBJ *,GOBJ *,float,int);\n'+text
        text=text.replace('        PortContact *e = &events[i];',
            f'        PortContact *e = &events[i];\n        {on_contact}(e->source,e->target,e->damage,e->shield);')
    return text.splitlines()
