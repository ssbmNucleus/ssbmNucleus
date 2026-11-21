"""Small shared article primitives; adapters supply the move's actual rules.

The fan uses a caller-owned item slot and a ready flag in var1. Geometry helpers
test an actual swept segment, not a fighter-distance substitute for native hits.
"""
import math


def fan_schedule(windows, prefix, *, count, angle, spread):
    if isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= 16:
        raise ValueError('fan count must be 1..16')
    if not all(math.isfinite(float(v)) for v in (angle, spread)):
        raise ValueError('fan angles must be finite')
    result=[]
    for first,name,length in windows:
        if name.startswith(prefix) and name[len(prefix):].isdigit():
            if first < 1 or length < 1:raise ValueError('fan window has no duration')
            result.append(dict(frame=int(first),count=count,angle=math.radians(angle),spread=math.radians(spread)))
    if not result:raise ValueError('fan has no source emission windows')
    if len({r['frame'] for r in result})!=len(result):raise ValueError('overlapping fan emission windows')
    return result


SOURCE=r'''
static int Port_SegmentCircle(float ax,float ay,float bx,float by,float cx,float cy,float radius)
{
    float dx=bx-ax,dy=by-ay,length=dx*dx+dy*dy,t=0;
    if(radius<0)return 0;
    if(length>0.000001f)t=((cx-ax)*dx+(cy-ay)*dy)/length;
    if(t<0)t=0;if(t>1)t=1;
    dx=ax+t*dx-cx;dy=ay+t*dy-cy;
    return dx*dx+dy*dy<=radius*radius;
}
static void Port_FireFan(GOBJ *owner,int slot,Vec3 at,int count,float angle,float spread,float speed,float offset)
{
    FighterData *fd=owner->userdata;int i;float a,c,s;Vec3 point;GOBJ *item;
    if(count<1 || count>16)return;
    for(i=0;i<count;i++)
    {
        a=angle+(i-(count-1)*0.5f)*spread;c=cos(a);s=sin(a);point=at;
        point.X+=(offset-speed)*c*fd->facing_direction;
        point.Y+=(offset-speed)*s;
        item=Make_Item(owner,slot,&point);
        if(item)
        {
            ItemData *id=item->userdata;
            id->self_vel.X=speed*c*fd->facing_direction;id->self_vel.Y=speed*s;
            id->item_var.var1=1;
        }
    }
}
'''
