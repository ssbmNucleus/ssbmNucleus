"""Native damage-driven item redirection; no proximity or attack-button hits."""
SOURCE=r'''
static void Port_EnableBatHurtbox(GOBJ *item,float radius)
{
    ItemData *id=item->userdata;
    // Item_CreateHurtbox only writes geometry. Projectile templates have zero
    // hurtboxes, so register the count and root joint before enabling contact.
    // MexTK declares hurt_num as int; GALE01 loads a BYTE at 0xAC8.
    // Store through a byte alias so big-endian PPC does not read zero.
    *((unsigned char *)&id->hurt_num)=1;id->it_hurt[0].jobj=item->hsd_object;
    id->it_hurt[0].is_updated=0;
    Item_CreateHurtbox(item,0,0,0,0,0,0,radius);
    Item_SetHurtboxTangibility(item,0);id->xdce1=1;
}
static int Port_BatItem(GOBJ *item,float *charge,float speed_min,float speed_max)
{
    ItemData *id=item->userdata;GOBJ *hitter=id->dmg.source_fighter;
    float damage=(float)id->dmg.recent,scale,angle,direction=id->dmg.takedmg_direction;
    if(damage<=0)return 0;
    scale=(damage-8.0f)/7.0f;if(scale<0)scale=0;if(scale>1)scale=1;
    *charge+=0.25f+0.5f*scale;if(*charge>1)*charge=1;
    if(hitter && hitter->userdata)
        direction=((FighterData *)hitter->userdata)->phys.pos.X>id->pos.X ? -1.0f : 1.0f;
    if(direction==0)direction=id->facing_direction;
    angle=(id->dmg.angle>=0 && id->dmg.angle<=360 ? id->dmg.angle : 45)*0.01745329252f;
    id->self_vel.X=cos(angle)*(speed_min+(speed_max-speed_min)*scale)*direction;
    id->self_vel.Y=sin(angle)*(speed_min+(speed_max-speed_min)*scale);
    id->facing_direction=id->self_vel.X<0 ? -1 : 1;
    Item_ResetAllHitPlayers(id);
    return 1;
}
'''
